"""Live route engine for the API.

Wraps Miguel's unchanged routing/ package and builds the same JSON objects as
base44_handoff/ (routes.json, emergency.json). Nothing here changes the model:
every number comes from routing/planner.py with routing/config.py.

Every metric, segment, geometry and point object is built by
routing.export_handoff.Exporter (Miguel's current engine, the one that produced the
28-route base44_handoff), so the API and the saved files have a single source.
This module only adds what an HTTP API needs: reading positions, errors, and
running the engine for any start/destination instead of the fixed ones.
"""
import json
import math
import os
import threading

import numpy as np

from routing import config as C
from routing.export_handoff import GROUPS, Exporter, r1
from routing.planner import Planner
from routing.terrain import line_of_sight, load_area, sky_blocked_fraction

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRID_NAME = "grid5m_jezero_crop"
GRID_DIR = os.environ.get("MARSWALK_GRID", os.path.join(ROOT, "data", GRID_NAME))
HANDOFF_DIR = os.environ.get("MARSWALK_HANDOFF", os.path.join(ROOT, "base44_handoff"))
HABITAT_LAT, HABITAT_LON = 18.452739, 77.405768
R_MARS = 3396190.0
BLOCK_REASON = {1: "no elevation data", 2: "west of the DTM artefact zone (lon < 77.35 E)",
                3: "thermal inertia below 100 (possibly not load-bearing)"}
CONF = {2: "high", 1: "medium", 0: "none"}


class ApiError(Exception):
    def __init__(self, status, code, detail):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


def _hav(la1, lo1, la2, lo2):
    return 2 * R_MARS * math.asin(math.sqrt(
        math.sin(math.radians(la2 - la1) / 2) ** 2 +
        math.cos(math.radians(la1)) * math.cos(math.radians(la2)) * math.sin(math.radians(lo2 - lo1) / 2) ** 2))


def _load(name):
    with open(os.path.join(HANDOFF_DIR, name), encoding="utf-8") as f:
        return json.load(f)


class Engine:
    def __init__(self):
        self.lock = threading.Lock()
        self.waypoints_doc = _load("waypoints.json")
        self.minerals_doc = _load("minerals.json")
        self.manifest = _load("layers_manifest.json")
        self.routes_doc = _load("routes.json")
        self.emergency_doc = _load("emergency.json")
        cond = _load("conditions.json")
        rad = cond.get("radiation") or {}
        # dose rate R in uGy/h (route_model.json -> radiation): median of Curiosity RAD, per day / 24
        self.rad_rate = rad["median_uGy_per_day"] / 24.0 if rad.get("median_uGy_per_day") else None
        self.wp = {w["id"]: w for w in self.waypoints_doc["waypoints"]}
        self.stops = [w for w in self.waypoints_doc["waypoints"] if w["type"] == "scientific_stop"]
        self.shelters = [w for w in self.waypoints_doc["waypoints"] if w["type"] == "candidate_shelter"]

        # Same window as export_handoff: farthest stop + 800 m (about +/-1.37 km)
        far = max(_hav(HABITAT_LAT, HABITAT_LON, s["lat"], s["lon"]) for s in self.stops)
        self.half_m = far + 800.0
        self.a = a = load_area(GRID_DIR, HABITAT_LON, HABITAT_LAT, self.half_m)
        self.p = Planner(a)
        self.base = a.lonlat_to_rc(HABITAT_LON, HABITAT_LAT)
        self.wp_rc = {k: a.lonlat_to_rc(w["lon"], w["lat"]) for k, w in self.wp.items()}
        self.walk = self.p.block == 0
        self.sky = sky_blocked_fraction(a, radius_m=500.0)  # same radius as the export
        self.sky0 = np.nan_to_num(self.sky, nan=0.0)
        self.los = line_of_sight(a, *self.base)
        self.los_walk = np.flatnonzero((self.los & self.walk).ravel())
        # Same set-up as export_handoff.main(): Exporter + safe-place times + dose-rate grid
        self.X = X = Exporter(a, self.p, self.base)
        self.safe_ids = ["habitat_01"] + [s["id"] for s in self.shelters]
        T = np.vstack([self.p.tree(self.wp_rc[s], 1.0, reverse=True)[0] for s in self.safe_ids])
        X.safe_time, X.safe_arg, X.safe_names = T.min(axis=0), T.argmin(axis=0), list(self.safe_ids)
        del T
        # R = Curiosity RAD median (conditions.json, written by export_handoff.rad_summary), per hour
        X.dose_rate = None if self.rad_rate is None else self.rad_rate * (1.0 - self.sky0)

    # ------------------------------------------------------------------ positions
    def pt(self, rc):
        return self.X.pt(rc)

    def resolve(self, pos, field="position", need_walkable=True):
        """pos: {"waypoint_id"} | {"east_m","north_m"} | {"lat","lon"} -> (rc, waypoint_id or None)."""
        if pos is None:
            return self.base, "habitat_01"
        if not isinstance(pos, dict):
            raise ApiError(422, "invalid_position", f"{field} must be an object")
        a = self.a
        if pos.get("waypoint_id") is not None:
            wid = pos["waypoint_id"]
            if wid not in self.wp_rc:
                raise ApiError(404, "unknown_waypoint", f"{field}: waypoint_id '{wid}' is not in waypoints.json")
            return self.wp_rc[wid], wid
        if pos.get("east_m") is not None and pos.get("north_m") is not None:
            e, n = float(pos["east_m"]), float(pos["north_m"])
            if not (math.isfinite(e) and math.isfinite(n)):
                raise ApiError(422, "invalid_position", f"{field}: east_m/north_m must be finite numbers")
            rc = (self.base[0] - int(round(n / a.dy)), self.base[1] + int(round(e / a.dx)))
        elif pos.get("lat") is not None and pos.get("lon") is not None:
            la, lo = float(pos["lat"]), float(pos["lon"])
            if not (math.isfinite(la) and math.isfinite(lo)):
                raise ApiError(422, "invalid_position", f"{field}: lat/lon must be finite numbers")
            x, y = math.radians(lo) * a.R, math.radians(la) * a.R
            rc = (int(math.floor((a.y0 - y) / a.cell)), int(math.floor((x - a.x0) / a.cell)))
        else:
            raise ApiError(422, "invalid_position", f"{field}: give waypoint_id, east_m+north_m, or lat+lon")
        H, W = a.shape
        if not (0 <= rc[0] < H and 0 <= rc[1] < W):
            raise ApiError(422, "outside_grid", f"{field} is outside the API grid (about +/-{self.half_m:.0f} m "
                           f"around the habitat)")
        if need_walkable and not self.walk[rc]:
            why = BLOCK_REASON.get(int(self.p.block[rc]), "blocked cell")
            raise ApiError(422, "not_walkable", f"{field} is on a cell nobody can enter: {why}")
        return rc, None

    # ------------------------------------------------------------------ metrics (all from the engine)
    def metrics(self, nodes):
        mt = self.X.metrics(nodes)
        if len(nodes) < 2 and self.X.dose_rate is not None:
            # emergency only: the astronaut is already on that cell; a walk of zero steps has zero
            # walking dose by the engine's own definition (sum over steps). Exporter.dose skips it.
            mt.setdefault("radiation_dose_estimate_uGy", 0.0)
        return mt

    @staticmethod
    def warnings(mt):
        if not mt["m_steeper_than_20deg"]:
            return []
        return [f"{mt['m_steeper_than_20deg']:.0f} m on ground or grade steeper than 20 deg (NASA Artemis suit "
                f"reference); steepest ground {mt['max_terrain_slope_deg']:.0f} deg, steepest walking grade "
                f"{mt['max_slope_deg']:.0f} deg"]

    def segments(self, nodes):
        return self.X.segments(nodes)

    def geometry(self, nodes):
        return self.X.geometry(nodes)

    def lonlat(self, nodes):
        return self.X.latlon(nodes)

    def route(self, rid, typ, label, nodes, dwell_min, n_stops, start_id, extra):
        mt = self.metrics(nodes)
        sci = dwell_min * n_stops
        total = mt["time_min"] + sci
        d = {"id": rid, "type": typ, "label": label, "start_waypoint_id": start_id}
        d.update(extra)
        d.update({"geometry": self.geometry(nodes), "lonlat": self.lonlat(nodes), **mt,
                  "science_time_min": float(sci), "total_time_min": r1(total),
                  "feasible_recommended_6h": total <= C.EVA_NOMINAL_H * 60,
                  "feasible_max_8h": total <= C.EVA_MAX_H * 60,
                  "warnings": self.warnings(mt),
                  "segments": self.segments(nodes),
                  "start": self.pt(self.p.rc(nodes[0])), "end": self.pt(self.p.rc(nodes[-1]))})
        return d

    # ------------------------------------------------------------------ route requests
    def _pair(self, a_rc, b_rc, w, round_trip):
        out = self.p.path(a_rc, b_rc, w)
        if out is None:
            raise ApiError(422, "no_route", "no walkable route connects these two points")
        if not round_trip:
            return out
        back = self.p.path(b_rc, a_rc, w)
        if back is None:
            raise ApiError(422, "no_route", "no walkable route back to the start")
        return out + back[1:]

    def _rid(self, a_id, b_id, typ):
        if a_id == "habitat_01" and b_id:
            return f"route_{b_id}_{typ}"
        return f"route_{a_id or 'point'}_to_{b_id or 'point'}_{typ}"

    def single(self, frm, to, kind, round_trip=True, dwell_min=C.DEFAULT_DWELL_MIN):
        a_rc, a_id = self.resolve(frm, "from")
        b_rc, b_id = self.resolve(to, "to")
        if a_rc == b_rc:
            raise ApiError(422, "same_point", "from and to are the same grid cell")
        w, label = (1.0, "fastest") if kind == "fastest" else (0.0, "preferred (least effort)")
        nodes = self._pair(a_rc, b_rc, w, round_trip)
        return self.route(self._rid(a_id, b_id, kind), kind, label, nodes, dwell_min, 1, a_id,
                          {"destination_waypoint_id": b_id, "round_trip": round_trip})

    def pareto(self, frm, to, round_trip=True, dwell_min=C.DEFAULT_DWELL_MIN, weights=(1.0, 0.75, 0.5, 0.25, 0.0)):
        a_rc, a_id = self.resolve(frm, "from")
        b_rc, b_id = self.resolve(to, "to")
        if a_rc == b_rc:
            raise ApiError(422, "same_point", "from and to are the same grid cell")
        alts = self.p.alternatives(a_rc, b_rc, weights=weights)
        if not alts:
            raise ApiError(422, "no_route", "no walkable route connects these two points")
        out = []
        for al in alts:
            lab = al["label"]
            if lab == "preferred (fastest & least effort)":
                typ = "fastest_and_easiest"
            elif lab.startswith("fastest"):
                typ = "fastest"
            elif "least effort" in lab:
                typ = "easiest"
            else:
                typ = "pareto"
            nodes = al["nodes"]
            if round_trip:
                back = self.p.path(b_rc, a_rc, al["w_time"])
                if back is None:
                    raise ApiError(422, "no_route", "no walkable route back to the start")
                nodes = nodes + back[1:]
            rid = self._rid(a_id, b_id, typ)
            if any(r["id"] == rid for r in out):
                rid = f"{rid}_w{al['w_time']}"
            out.append(self.route(rid, typ, lab, nodes, dwell_min, 1, a_id,
                                  {"destination_waypoint_id": b_id, "round_trip": round_trip}))
        out.sort(key=lambda r: (r["time_min"], -r["relative_effort"]))  # by time; ties: fastest first
        return out

    def mineral_target(self, mineral, frm, dwell_min):
        if mineral not in GROUPS:
            raise ApiError(422, "unknown_mineral", "mineral must be carbonate, olivine or clay")
        out = []
        for s in self.stops:
            if s.get("mineral_group") == mineral:
                out += self.pareto(frm, {"waypoint_id": s["id"]}, True, dwell_min)
        return out

    def tour(self, frm, stop_ids, dwell_min, budget_h, label):
        a_rc, a_id = self.resolve(frm, "from")
        rcs = [self.wp_rc[s] for s in stop_ids]
        t = self.p.best_tour(a_rc, rcs, 0.0, dwell_min / 60.0, budget_h)
        if not t:
            return None
        nodes = t["paths"][0]
        for leg in t["paths"][1:]:
            nodes = nodes + leg[1:]
        ids = [a_id or "start"] + list(stop_ids)
        k = len(t["order"]) - 2
        return self.route("route_budget_live", "multi_stop", label, nodes, dwell_min, k, a_id,
                          {"stop_order": [ids[i] for i in t["order"]], "round_trip": True, "time_budget_h": budget_h})

    def time_budget(self, budget_min, frm, dwell_min, multi_stop):
        single = []
        for s in self.stops:
            try:
                r = self.single(frm, {"waypoint_id": s["id"]}, "easiest", True, dwell_min)
            except ApiError as e:
                if e.code in ("same_point", "no_route"):
                    continue
                raise
            if r["total_time_min"] <= budget_min:
                single.append(r)
        single.sort(key=lambda r: r["total_time_min"])
        best = None
        if multi_stop:
            h = budget_min / 60.0
            hs = f"{h:g}"
            best = self.tour(frm, [s["id"] for s in self.stops], dwell_min, h,
                             f"most stops within {hs} h, least effort")
        return single, best

    def via_shelter(self, frm, to, dwell_min):
        """start -> best terrain shelter -> destination -> start, least effort.
        Same selection as export_handoff.main() ("shelters as intermediate stops"): the shelter
        that minimises the summed least-effort cost of the three legs."""
        a_rc, a_id = self.resolve(frm, "from")
        b_rc, b_id = self.resolve(to, "to")
        if a_rc == b_rc:
            raise ApiError(422, "same_point", "from and to are the same grid cell")
        p = self.p
        start_tree = p.tree(a_rc, 0.0)
        dest_tree = p.tree(b_rc, 0.0)
        best = None
        for s in self.shelters:
            rc = self.wp_rc[s["id"]]
            sh_tree = p.tree(rc, 0.0)
            cost = start_tree[0][p.idx(rc)] + sh_tree[0][p.idx(b_rc)] + dest_tree[0][p.idx(a_rc)]
            if np.isfinite(cost) and (best is None or cost < best[0]):
                best = (cost, s["id"], sh_tree)
        if best is None:
            raise ApiError(422, "no_route", "no terrain shelter can be visited on the way")
        _, sh, sh_tree = best
        legs = [p._walk(start_tree[1], p.idx(self.wp_rc[sh])), p._walk(sh_tree[1], p.idx(b_rc)),
                p._walk(dest_tree[1], p.idx(a_rc))]
        nodes = legs[0] + legs[1][1:] + legs[2][1:]
        rid = f"route_{b_id}_via_shelter" if a_id == "habitat_01" and b_id else \
            f"route_{a_id or 'point'}_to_{b_id or 'point'}_via_shelter"
        r = self.route(rid, "via_shelter", f"via {sh} (least effort)", nodes, dwell_min, 1, a_id,
                       {"stop_order": [a_id or "start", sh, b_id or "destination", a_id or "start"],
                        "round_trip": True, "destination_waypoint_id": b_id, "via_waypoint_id": sh})
        direct = self.single(frm, to, "easiest", True, dwell_min)
        r["extra_time_vs_easiest_min"] = r1(r["total_time_min"] - direct["total_time_min"])
        r["extra_effort_vs_easiest"] = r1(r["relative_effort"] - direct["relative_effort"], 3)
        return r

    # ------------------------------------------------------------------ emergency
    def emergency(self, position, o2_h, margin):
        here, here_id = self.resolve(position, "position")
        p = self.p
        targets = [("habitat_01", "base", self.wp_rc["habitat_01"])] + \
                  [(s["id"], "candidate_shelter", self.wp_rc[s["id"]]) for s in self.shelters]
        dist_here, _ = p.tree(here, 0.0)
        if len(self.los_walk):
            targets.append(("comms_nearest_los", "communication_point",
                            p.rc(self.los_walk[np.argmin(dist_here[self.los_walk])])))
        res = p.emergency(here, o2_h, targets, margin=margin)
        opts = []
        for o in res["options"]:
            if not o.get("reachable", True):
                opts.append({"destination_id": o["name"], "kind": o["kind"], "reachable": False})
                continue
            nodes = o["nodes"]
            d = {"destination_id": o["name"], "kind": o["kind"], "reachable": True,
                 "feasible_under_model": bool(o["feasible"]), **self.metrics(nodes), "geometry": self.geometry(nodes)}
            if o["kind"] == "communication_point":
                d["destination"] = self.pt(p.rc(nodes[-1]))
            opts.append(d)
        out = {}
        if here_id:
            out["id"] = f"emergency_{here_id}_live"
            out["start_waypoint_id"] = here_id
        out.update({"start": self.pt(here), "suit_supply_left_h": o2_h, "reserve_fraction": margin,
                    "usable_h": r1(res["usable_o2_h"], 2),
                    "route_choice": "least effort (least oxygen under the model)",
                    "oxygen_verified": False, "destinations": opts})
        return out

    # ------------------------------------------------------------------ terrain point
    def point(self, pos):
        rc, _ = self.resolve(pos, "point", need_walkable=False)
        a = self.a
        q = self.pt(rc)
        cls = int(a.mineral[rc])
        group = next((g for g, s in GROUPS.items() if cls in s), None)
        ti = float(a.ti[rc])
        sky = self.sky[rc]
        return {"east_m": q["east_m"], "north_m": q["north_m"], "lat": q["lat"], "lon": q["lon"],
                "elevation_m": q["elevation_m"], "slope_deg": r1(a.slope[rc]), "roughness_deg": r1(a.rough[rc]),
                "thermal_inertia": r1(ti) if ti > 0 else None,
                "mineral": {"class": cls, "name": a.minerals.get(cls), "group": group,
                            "confidence": CONF.get(int(a.mconf[rc]), "none")},
                "walkable": bool(self.walk[rc]),
                "sky_blocked_pct": r1(100 * sky) if np.isfinite(sky) else None,
                "line_of_sight_to_habitat": bool(self.los[rc])}
