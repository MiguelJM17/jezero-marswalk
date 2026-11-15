"""Export everything the Base44 app needs (the app handoff README) into one folder.

Usage (from the project root):
  python -m routing.export_handoff --stops curated/proposed_stops.csv --option A \
      --base-lat 18.452739 --base-lon 77.405768 --out outputs

All values are computed from the processed NASA layers and the routing model in
routing/config.py. Nothing is filled in by hand.
"""
import argparse
import csv
import glob
import itertools
import json
import math
import os
import time

import numpy as np
from scipy import ndimage

from . import config as C
from .planner import Planner, metabolic_rel, standing_rel, tobler_kmh
from .terrain import line_of_sight, load_area, sky_blocked_fraction

FRAME = {
    "name": "local ENU from habitat",
    "axes": ["east_m", "north_m"],
    "origin": "habitat_01",
    "units": "metres on the ground",
    "note": ("east_m/north_m are ground metres from the habitat. lat/lon are planetocentric degrees, "
             "longitude positive east, Mars 2000 sphere (R = 3,396,190 m). x_m/y_m are coordinates in "
             "the DTM's equirectangular projection (standard parallel 0, central meridian 0). "
             "This is NOT RFC 7946 (Earth WGS84) GeoJSON."),
}
GROUPS = {"carbonate": {2}, "olivine": {1}, "clay": {3, 9, 10}}
GROUP_LABEL = {"carbonate": "Probable Mg-carbonate", "olivine": "Probable olivine", "clay": "Probable clay"}
CRISM_SRC = "CRISM mineral map of Jezero (Parente, Itoh, Saranathan), https://zenodo.org/record/5575824"


def r1(x, n=1):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), n)


def supply(walking_h, science_min):
    """Suit supply for a route: walking plus the time spent standing at the stops.

    `relative_effort` counts walking only. Standing at a stop still consumes supply
    (Pandolf's standing term, standing_rel() = 0.5 of the flat walking rate), so a
    route that includes science time costs more than its walking figure says."""
    sci = (science_min / 60.0) * standing_rel()
    return {"supply_h_walking": r1(walking_h, 3),
            "supply_h_science": r1(sci, 3),
            "supply_h_total": r1(walking_h + sci, 3),
            "supply_pct_of_suit": r1(100.0 * (walking_h + sci) / C.EVA_MAX_H, 1)}


class Exporter:
    def __init__(self, a, p, base):
        self.a, self.p, self.base = a, p, base

    def pt(self, rc):
        r, c = int(rc[0]), int(rc[1])
        lon, lat = self.a.rc_to_lonlat(r, c)
        x, y = self.a.rc_to_map(r, c)
        e, n = self.a.enu(r, c, *self.base)
        return {"east_m": r1(e), "north_m": r1(n), "lat": round(lat, 6), "lon": round(lon, 6),
                "x_m": r1(x), "y_m": r1(y), "elevation_m": r1(self.a.z[r, c])}

    def segments(self, nodes, every=10):
        out = []
        for k in range(0, len(nodes) - 1, every):
            seg = nodes[k:min(len(nodes), k + every + 1)]
            st = self.p.stats(seg)
            a0, a1 = self.pt(self.p.rc(seg[0])), self.pt(self.p.rc(seg[-1]))
            out.append({"start": [a0["east_m"], a0["north_m"]], "end": [a1["east_m"], a1["north_m"]],
                        "distance_m": r1(st["distance_m"]), "time_min": r1(st["time_h"] * 60),
                        "relative_effort": r1(st["effort_o2_h"], 3), "max_slope_deg": r1(st["max_grade_deg"]),
                        "max_terrain_slope_deg": self.terrain(seg)["max_terrain_slope_deg"],
                        "elevation_change_m": r1(a1["elevation_m"] - a0["elevation_m"]),
                        **self.nearest_safe(seg)})
        return out

    def nearest_safe(self, nodes):
        """Nearest safe place (habitat or terrain shelter) by walking time, from the segment's midpoint,
        and the worst case along the segment."""
        if getattr(self, "safe_time", None) is None:
            return {}
        idx = np.asarray(nodes)
        mid = idx[len(idx) // 2]
        worst = float(np.max(self.safe_time[idx]))
        return {"nearest_safe_place_id": self.safe_names[int(self.safe_arg[mid])],
                "time_to_nearest_safe_place_min": r1(self.safe_time[mid] * 60),
                "max_time_to_nearest_safe_place_min": r1(worst * 60)}

    def geometry(self, nodes):
        coords = []
        for i in nodes:
            q = self.pt(self.p.rc(i))
            coords.append([q["east_m"], q["north_m"]])
        return {"type": "LineString", "frame": "local ENU from habitat", "coordinates": coords}

    def latlon(self, nodes):
        return [[self.pt(self.p.rc(i))["lon"], self.pt(self.p.rc(i))["lat"]] for i in nodes]

    def terrain(self, nodes):
        """Terrain slope (steepest direction of the ground, from the slope layer) along the path."""
        rc = np.array([self.p.rc(i) for i in nodes])
        sl = np.nan_to_num(self.a.slope[rc[:, 0], rc[:, 1]], nan=0.0)
        d = np.hypot(np.diff(rc[:, 1]) * self.a.dx, np.diff(rc[:, 0]) * self.a.dy)
        z = self.a.z[rc[:, 0], rc[:, 1]]
        grade = np.degrees(np.arctan(np.abs(np.diff(z)) / d))
        return {"max_terrain_slope_deg": r1(sl.max()),
                "m_terrain_steeper_than_20deg": r1(d[sl[1:] > C.MAX_SLOPE_DEG].sum()),
                "m_walking_grade_steeper_than_20deg": r1(d[grade > C.MAX_SLOPE_DEG].sum()),
                **self.dose(rc, d, z)}

    def dose(self, rc, d, z):
        """Estimated dose along the path: walking time of each step x reference dose rate x (1 - sky hidden).
        Geometric estimate only (see route_model.json -> radiation)."""
        if getattr(self, "dose_rate", None) is None or len(rc) < 2:
            return {}
        eta = self.p.eta[rc[:, 0], rc[:, 1]]
        t, _ = self.p._edge_costs(np.diff(z) / d, d, eta[:-1], eta[1:])
        rate = self.dose_rate[rc[1:, 0], rc[1:, 1]]
        return {"radiation_dose_estimate_uGy": r1(float(np.sum(t / 3600.0 * rate)), 2)}

    def metrics(self, nodes):
        st = self.p.stats(nodes)
        return {"distance_m": r1(st["distance_m"]), "time_min": r1(st["time_h"] * 60),
                "relative_effort": r1(st["effort_o2_h"], 3), "max_slope_deg": r1(st["max_grade_deg"]),
                "climb_m": r1(st["climb_m"]), "descent_m": r1(st["descent_m"]),
                "m_steeper_than_20deg": r1(st.get("m_above_slope_limit", 0.0)),
                "max_side_slope_deg": r1(st.get("max_side_slope_deg", 0.0)),
                "m_side_slope_steeper_than_20deg": r1(st.get("m_side_slope_over_reference", 0.0)),
                **self.terrain(nodes)}


def rad_summary(rad_dir, days=30):
    try:
        import cdflib
    except ImportError:
        return None
    files = sorted(glob.glob(os.path.join(rad_dir, "*.cdf")))
    if not files:
        return None
    T, D = [], []
    for f in files[-days:]:
        c = cdflib.CDF(f)
        t = np.atleast_1d(c.varget("EPOCH")).astype(np.int64)
        d = np.atleast_2d(c.varget("DOSIMETRY_TOTAL"))[:, 1].astype(float)  # 'RTG Corrected Dose B'
        fl = np.array([str(x).strip() for x in np.atleast_1d(c.varget("FLAGGED_DATA"))])
        ok = (fl == "") & np.isfinite(d) & (d > 0)
        T += list(t[ok])
        D += list(d[ok])
    s = cdflib.cdfepoch.encode(np.array(T, np.int64))
    return {"quantity": "RTG Corrected Dose B (dose rate in silicon, Curiosity's generator contribution removed)",
            "median_uGy_per_day": r1(np.median(D)), "n_observations": len(D),
            "from_utc": str(s[0])[:19], "to_utc": str(s[-1])[:19],
            "location": "Gale crater (Curiosity). NOT measured at Jezero.",
            "source": "MSL RAD Level 2 observations, NASA CDAWeb, https://cdaweb.gsfc.nasa.gov/sp_phys/data/msl/rad/cdf/obs-l2/",
            "quality": "observations flagged in FLAGGED_DATA excluded"}


def save_png(path, rgba):
    from PIL import Image
    Image.fromarray(rgba).save(path, optimize=True)


def colorize(x, lo, hi, cmap, mask=None, alpha=200):
    import matplotlib
    cm = matplotlib.colormaps[cmap]
    v = np.clip((x - lo) / (hi - lo), 0, 1)
    rgba = (cm(np.nan_to_num(v)) * 255).astype(np.uint8)
    rgba[..., 3] = alpha
    bad = ~np.isfinite(x) if mask is None else ~mask
    rgba[bad, 3] = 0
    return rgba


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", default="data/processed/grid5m")
    ap.add_argument("--stops", required=True)
    ap.add_argument("--option", default="A")
    ap.add_argument("--base-lat", type=float, required=True)
    ap.add_argument("--base-lon", type=float, required=True)
    ap.add_argument("--rad", default="data/rad")
    ap.add_argument("--dwell-min", type=float, default=C.DEFAULT_DWELL_MIN)
    ap.add_argument("--photos", default=None, help="Ronald's photo_table.csv")
    ap.add_argument("--meda", default="data/meda_pressure_summary.json", help="pressure summary from MEDA PS files")
    ap.add_argument("--rover", default="curated/rover_waypoints_minerals.csv", help="Perseverance end-of-drive positions (Ronald)")
    ap.add_argument("--out", default="outputs")
    A = ap.parse_args()
    t0 = time.time()
    os.makedirs(os.path.join(A.out, "map_layers"), exist_ok=True)

    # ---------------- stops from Ronald's CSV
    stops = []
    counts = {}
    for r in csv.DictReader(open(A.stops, encoding="utf-8")):
        if r.get("opcion") != A.option or r.get("grupo") == "habitat":
            continue
        g = r["grupo"]
        counts[g] = counts.get(g, 0) + 1
        stops.append({"id": f"{g}_{counts[g]:02d}", "group": g, "lat": float(r["lat"]), "lon": float(r["lon"]),
                      "mineral": r["mineral"], "mineral_class": int(r["mineral_clase"]),
                      "photo": {"rover_sol_from": int(r["foto_sol_desde"]), "rover_sol_to": int(r["foto_sol_hasta"]),
                                "rover_site_drive": r["foto_rmc_site_drive"],
                                "distance_photo_position_to_stop_m": float(r["dist_foto_a_parada_m"])}})

    R = 3396190.0
    hav = lambda la1, lo1, la2, lo2: 2 * R * math.asin(math.sqrt(
        math.sin(math.radians(la2 - la1) / 2) ** 2 +
        math.cos(math.radians(la1)) * math.cos(math.radians(la2)) * math.sin(math.radians(lo2 - lo1) / 2) ** 2))
    far = max(hav(A.base_lat, A.base_lon, s["lat"], s["lon"]) for s in stops)
    half = far + 800.0
    a = load_area(A.grid, A.base_lon, A.base_lat, half)
    p = Planner(a)
    base = a.lonlat_to_rc(A.base_lon, A.base_lat)
    X = Exporter(a, p, base)
    for s in stops:
        s["rc"] = a.lonlat_to_rc(s["lon"], s["lat"])
    H, W = a.shape
    rr, cc = np.mgrid[0:H, 0:W]
    dist_base = np.hypot((cc - base[1]) * a.dx, (base[0] - rr) * a.dy)
    walk = p.block == 0
    print(f"area {H}x{W} ({len(p.t)} edges) {time.time()-t0:.1f}s", flush=True)

    # ---------------- shelters: most sky blocked, but only on walkable ground <= 20 deg
    sky = sky_blocked_fraction(a, radius_m=500.0)
    gentle = walk & (np.nan_to_num(a.slope, nan=90) <= C.MAX_SLOPE_DEG) & (dist_base <= far + 400)
    score = np.where(gentle, np.nan_to_num(sky, nan=0), -1).ravel()
    shelters = []
    for i in np.argsort(-score, kind="stable"):
        if score[i] <= 0 or len(shelters) == 6:
            break
        r, c = divmod(int(i), W)
        if all(math.hypot((r - q[0]) * a.dy, (c - q[1]) * a.dx) >= 200 for q in shelters):
            shelters.append((r, c))
    los = line_of_sight(a, *base)
    # walking time (h, fastest route) from every cell to each safe place (reverse Dijkstra)
    safe = [("habitat_01", base)] + [(f"shelter_{i+1:02d}", rc) for i, rc in enumerate(shelters)]
    T = np.vstack([p.tree(rc, 1.0, reverse=True)[0] for _, rc in safe])
    X.safe_time, X.safe_arg, X.safe_names = T.min(axis=0), T.argmin(axis=0), [n for n, _ in safe]
    rad = rad_summary(A.rad)
    rad_rate_h = rad["median_uGy_per_day"] / 24.0 if rad else None
    X.dose_rate = None if rad_rate_h is None else rad_rate_h * (1.0 - np.nan_to_num(sky, nan=0.0))
    del T
    print(f"sky + LOS + safe places {time.time()-t0:.1f}s", flush=True)

    # ---------------- mission_config.json
    b = X.pt(base)
    bounds_e = [r1(-(base[1] + 0.5) * a.dx), r1((W - base[1] - 0.5) * a.dx)]
    bounds_n = [r1((base[0] - H + 0.5) * a.dy), r1((base[0] + 0.5) * a.dy)]
    lon0, lat0 = a.rc_to_lonlat(0, 0)
    lon1, lat1 = a.rc_to_lonlat(H - 1, W - 1)
    mission = {
        "site": "Jezero Crater, Mars",
        "habitat": {"id": "habitat_01", "name": "Habitat A", **b,
                    "source": "Team option A (Ronald), moved 100 m east to flat ground (1.4 deg slope)"},
        "study_area": {"east_m": bounds_e, "north_m": bounds_n,
                       "lat_range": [round(min(lat0, lat1), 6), round(max(lat0, lat1), 6)],
                       "lon_range": [round(min(lon0, lon1), 6), round(max(lon0, lon1), 6)]},
        "grid": {"cell_size_m": a.cell, "ground_cell_east_m": r1(a.dx, 3), "ground_cell_north_m": a.dy,
                 "rows": H, "cols": W},
        "eva_limits": {"recommended_h": C.EVA_NOMINAL_H, "maximum_h": C.EVA_MAX_H, "planning_radius_m": C.OPERATING_RADIUS_M,
                       "label": "Planning assumptions from NASA Artemis references, not Mars-certified limits"},
        "slope_reference_deg": C.MAX_SLOPE_DEG,
        "slope_policy": "No terrain is forbidden for slope. Steep ground costs more and is avoided by the planner; "
                        "route length steeper than 20 deg is reported as a warning (team decision).",
        "masked": ["cells without DTM elevation", "thermal inertia < 100 (none in this area)",
                   f"west of lon {C.WEST_EDGE_LON} E (DTM artefact zone; assumption from our inspection, far from this area)"],
        "frame": FRAME,
        "crs_wkt": None,
    }
    gj = json.load(open(os.path.join(A.grid, "grid.json")))
    mission["crs_wkt"] = gj["crs_wkt"]

    # ---------------- waypoints.json
    wps = [{"id": "habitat_01", "type": "habitat", "name": "Habitat A", **b, "activity_min": 0,
            "source": mission["habitat"]["source"]}]
    for s in stops:
        wps.append({"id": s["id"], "type": "scientific_stop", "name": f"{GROUP_LABEL[s['group']]} {s['id'][-2:]}",
                    **X.pt(s["rc"]), "activity_min": A.dwell_min,
                    "mineral_group": s["group"], "mineral_label": f"{s['mineral'].split(' (')[0]} (probable detection)",
                    "photo": s["photo"],
                    "source": "Stop selection: Ronald (rover waypoints + CRISM layer); position from NASA M20 waypoints file + team grid"})
    if A.photos:
        alias = {"olivino": "olivine", "carbonato": "carbonate", "arcilla": "clay"}
        by = {}
        for r in csv.DictReader(open(A.photos, encoding="utf-8")):
            wid = r.get("waypoint_id") or "{}_{:02d}".format(alias[r["lugar"].split("-")[0]], int(r["lugar"].split("-")[1]))
            by.setdefault(wid, []).append({
                "camera": r["camara"].replace("izquierda", "left").replace("derecha", "right"), "sol": int(r["sol"]), "date_utc": r["fecha_utc"], "credit": r["credito"],
                "page_url": r["enlace_foto"], "image_url": r["enlace_descarga"], "file": "sol{:04d}_{}_{}.png".format(int(r["sol"]), "mastcamz" if "Mastcam" in r["camara"] else "navcam", wid),
                "rover_site_drive": r["posicion_rover_site_drive"],
                "distance_photo_position_to_stop_m": float(r["distancia_foto_a_parada_m"])})
        for w in wps:
            if w["id"] in by:
                w["photos"] = by[w["id"]]
                w["photo_note"] = ("Raw Perseverance images taken from the rover position closest to this stop. "
                                   "The camera direction is not confirmed: the photo shows the terrain seen from there, "
                                   "not necessarily the stop at the centre. Selection: Ronald.")
    # Perseverance positions inside the area; photo positions get their photos
    rover = []
    if A.rover and os.path.exists(A.rover):
        photos_by_sd = {}
        for w in wps:
            for ph in w.get("photos", []):
                photos_by_sd.setdefault(ph["rover_site_drive"], []).append({**ph, "stop_id": w["id"]})
        for r in csv.DictReader(open(A.rover, encoding="utf-8")):
            rc = a.lonlat_to_rc(float(r["lon"]), float(r["lat"]))
            if not (0 <= rc[0] < H and 0 <= rc[1] < W):
                continue
            q = X.pt(rc)
            q.update({"lat": round(float(r["lat"]), 6), "lon": round(float(r["lon"]), 6),
                      "elevation_m": float(r["elev_geoid_m"])})
            item = {"site_drive": r["rmc"], "sol_from": int(r["sol"]), "sol_to": int(r["next_sol"]), **q}
            if r["rmc"] in photos_by_sd:
                item["photos"] = photos_by_sd[r["rmc"]]
            rover.append(item)
        rover.sort(key=lambda d: d["sol_from"])
        for w in wps:
            for ph in w.get("photos", []):
                pos = next((d for d in rover if d["site_drive"] == ph["rover_site_drive"]), None)
                if pos:
                    ph["taken_from"] = {k: pos[k] for k in ("east_m", "north_m", "lat", "lon")}
    for i, rc in enumerate(shelters):
        wps.append({"id": f"shelter_{i+1:02d}", "type": "candidate_shelter", "name": f"Terrain shelter {chr(65+i)}",
                    **X.pt(rc), "sky_blocked_pct": r1(100 * sky[rc]),
                    **({"dose_rate_estimate_uGy_per_h": r1(X.dose_rate[rc], 2),
                        "dose_saving_vs_open_sky_pct": r1(100 * sky[rc])} if X.dose_rate is not None else {}),
                    "note": "Geometric sky-view proxy only. Not a life-support shelter; no oxygen or comms implied.",
                    "source": "Computed from HiRISE DTM (horizon angles, 16 azimuths, 500 m)"})

    # ---------------- minerals.json: high-confidence patches within the area
    minerals = []
    for g, cls in GROUPS.items():
        m = np.isin(a.mineral, list(cls)) & (a.mconf == 2) & (dist_base <= far + 400)
        lab, n = ndimage.label(m, structure=np.ones((3, 3)))
        sizes = ndimage.sum(m, lab, range(1, n + 1))
        for k in np.argsort(-sizes, kind="stable")[:15]:
            if sizes[k] < 10:
                continue
            cells = np.argwhere(lab == k + 1)
            cen = cells.mean(axis=0)
            crc = tuple(cells[np.argmin(((cells - cen) ** 2).sum(1))])
            q = X.pt(crc)
            near_stop = [s["id"] for s in stops if s["group"] == g and lab[s["rc"]] == k + 1]
            minerals.append({"id": f"{g}_patch_{len(minerals)+1:02d}", "group": g, "label": GROUP_LABEL[g],
                             "classes": sorted(int(c) for c in np.unique(a.mineral[lab == k + 1])),
                             "confidence": "high (CRISM map code)", "area_m2": r1(sizes[k] * a.dx * a.dy, 0),
                             "center": q,
                             "bbox_east_m": [r1(X.pt((0, cells[:, 1].min()))["east_m"]), r1(X.pt((0, cells[:, 1].max()))["east_m"])],
                             "bbox_north_m": [r1(X.pt((cells[:, 0].max(), 0))["north_m"]), r1(X.pt((cells[:, 0].min(), 0))["north_m"])],
                             "linked_waypoints": near_stop, "source": CRISM_SRC})

    # ---------------- routes.json: round trips habitat -> stop -> habitat
    routes = []
    for s in stops:
        alts = p.alternatives(base, s["rc"], weights=(1.0, 0.5, 0.0))
        for al in alts:
            out_nodes = al["nodes"]
            back = p.path(s["rc"], base, al["w_time"])
            nodes = out_nodes + back[1:]
            mt = X.metrics(nodes)
            total_min = mt["time_min"] + A.dwell_min
            lb = al["label"]
            typ = ("fastest_and_easiest" if "fastest &" in lb else "easiest" if "least effort" in lb
                   else "fastest" if lb == "fastest" else "pareto")
            routes.append({"id": f"route_{s['id']}_{typ}", "type": typ, "label": al["label"],
                           "start_waypoint_id": "habitat_01", "destination_waypoint_id": s["id"], "round_trip": True,
                           "geometry": X.geometry(nodes), "lonlat": X.latlon(nodes),
                           **mt, "science_time_min": A.dwell_min, "total_time_min": r1(total_min),
                           **supply(mt["relative_effort"], A.dwell_min),
                           "feasible_recommended_6h": total_min <= C.EVA_NOMINAL_H * 60,
                           "feasible_max_8h": total_min <= C.EVA_MAX_H * 60,
                           "warnings": ([f"{mt['m_steeper_than_20deg']:.0f} m on ground or grade steeper than 20 deg (NASA Artemis suit reference); steepest ground {mt['max_terrain_slope_deg']:.0f} deg, steepest walking grade {mt['max_slope_deg']:.0f} deg"]
                                        if mt["m_steeper_than_20deg"] else []),
                           "segments": X.segments(nodes)})
        print(f"routes {s['id']} {time.time()-t0:.1f}s", flush=True)

    def multi(rid, typ, label, legs, order_ids, n_science, extra=None):
        nodes = legs[0]
        for leg in legs[1:]:
            nodes = nodes + leg[1:]
        mt = X.metrics(nodes)
        tot = mt["time_min"] + A.dwell_min * n_science
        d = {"id": rid, "type": typ, "label": label, "start_waypoint_id": "habitat_01", "stop_order": order_ids,
             "round_trip": True, "geometry": X.geometry(nodes), "lonlat": X.latlon(nodes), **mt,
             "science_time_min": A.dwell_min * n_science, "total_time_min": r1(tot),
             **supply(mt["relative_effort"], A.dwell_min * n_science),
             "feasible_recommended_6h": tot <= C.EVA_NOMINAL_H * 60, "feasible_max_8h": tot <= C.EVA_MAX_H * 60,
             "warnings": ([f"{mt['m_steeper_than_20deg']:.0f} m on ground or grade steeper than 20 deg (NASA Artemis suit reference); steepest ground {mt['max_terrain_slope_deg']:.0f} deg, steepest walking grade {mt['max_slope_deg']:.0f} deg"]
                          if mt["m_steeper_than_20deg"] else []),
             **(extra or {}), "segments": X.segments(nodes)}
        return d

    # least-effort trees from the habitat, every stop and every shelter (reused below)
    ids = ["habitat_01"] + [s["id"] for s in stops]
    pts = [base] + [s["rc"] for s in stops]
    pmat = p.matrix(pts, 0.0)
    legst = {k: (p.stats(v) if v else None) for k, v in pmat.items()}

    def best_order(budget_h):
        best = None
        for k in range(len(stops), 0, -1):
            for sub in itertools.combinations(range(1, len(pts)), k):
                for order in itertools.permutations(sub):
                    seq = (0,) + order + (0,)
                    L = [legst[(seq[i], seq[i + 1])] for i in range(len(seq) - 1)]
                    if any(l is None for l in L):
                        continue
                    t = sum(l["time_h"] for l in L) + A.dwell_min / 60.0 * k
                    e = sum(l["effort_o2_h"] for l in L)
                    if t <= budget_h and (best is None or e < best[1]):
                        best = (seq, e)
            if best:
                return best[0]
        return None

    # full tour (all stops) with least effort, within the recommended time
    seq = best_order(C.EVA_NOMINAL_H)
    if seq and len(seq) == len(pts) + 1:
        routes.append(multi("route_tour_all_stops", "multi_stop", "all stops, least effort",
                            [pmat[(seq[i], seq[i + 1])] for i in range(len(seq) - 1)], [ids[i] for i in seq], len(seq) - 2))

    # "I have this much time": most stops that fit, then least effort, for several budgets
    budgets = []
    seen = {}
    for bh in (1, 1.5, 2, 3, 4, 6, 8):
        seq = best_order(bh)
        if not seq:
            budgets.append({"budget_h": bh, "route_id": None, "stops_visited": [], "note": "no stop fits in this time"})
            continue
        key = tuple(seq)
        if key not in seen:
            rid = f"route_budget_{str(bh).replace('.', '_')}h"
            routes.append(multi(rid, "multi_stop", f"most stops within {bh} h, least effort",
                                [pmat[(seq[i], seq[i + 1])] for i in range(len(seq) - 1)], [ids[i] for i in seq], len(seq) - 2,
                                {"time_budget_h": bh}))
            seen[key] = rid
        budgets.append({"budget_h": bh, "route_id": seen[key], "stops_visited": [ids[i] for i in seq[1:-1]]})
    print(f"tour + budgets {time.time()-t0:.1f}s", flush=True)

    # shelters as intermediate stops: habitat -> shelter -> stop -> habitat, best shelter per stop
    sh_ids = [f"shelter_{i+1:02d}" for i in range(len(shelters))]
    sh_tree = [p.tree(rc, 0.0) for rc in shelters]
    base_tree = p.tree(base, 0.0)
    stop_tree = {s["id"]: p.tree(s["rc"], 0.0) for s in stops}
    for s in stops:
        best = None
        for j, rc in enumerate(shelters):
            d1, d2, d3 = base_tree[0][p.idx(rc)], sh_tree[j][0][p.idx(s["rc"])], stop_tree[s["id"]][0][p.idx(base)]
            if not np.isfinite(d1 + d2 + d3):
                continue
            if best is None or d1 + d2 + d3 < best[0]:
                best = (d1 + d2 + d3, j)
        if best is None:
            continue
        j = best[1]
        legs = [p._walk(base_tree[1], p.idx(shelters[j])), p._walk(sh_tree[j][1], p.idx(s["rc"])),
                p._walk(stop_tree[s["id"]][1], p.idx(base))]
        direct = next((r for r in routes if r.get("destination_waypoint_id") == s["id"]
                       and r["type"] in ("easiest", "fastest_and_easiest")), None)
        r = multi(f"route_{s['id']}_via_shelter", "via_shelter", f"via {sh_ids[j]} (least effort)", legs,
                  ["habitat_01", sh_ids[j], s["id"], "habitat_01"], 1,
                  {"destination_waypoint_id": s["id"], "via_waypoint_id": sh_ids[j]})
        if direct:
            r["extra_time_vs_easiest_min"] = r1(r["total_time_min"] - direct["total_time_min"])
            r["extra_effort_vs_easiest"] = r1(r["relative_effort"] - direct["relative_effort"], 3)
        routes.append(r)
    print(f"via shelter {time.time()-t0:.1f}s", flush=True)

    routes_doc = {"site": "Jezero Crater", "frame": FRAME, "crs_wkt": mission["crs_wkt"],
                  "units": {"distance": "m", "time": "min", "relative_effort": "hours of suit supply at 1200 BTU/h (model, see route_model.json)"},
                  "field_definitions": {
                      "max_slope_deg": "steepest walking grade: slope in the direction the astronaut walks, cell to cell",
                      "max_terrain_slope_deg": "steepest ground slope under the route (slope of the terrain in its own steepest direction; a route can cross it sideways)",
                      "m_walking_grade_steeper_than_20deg": "metres where the walking grade exceeds 20 deg",
                      "m_terrain_steeper_than_20deg": "metres on ground whose terrain slope exceeds 20 deg",
                      "m_steeper_than_20deg": "metres where either of the two above exceeds 20 deg (used for warnings)",
                      "max_side_slope_deg": "steepest side slope: the cross-slope the astronaut walks across, from tan(terrain)^2 = tan(grade)^2 + tan(side)^2. Neither the speed nor the effort model prices it unless SIDE_SLOPE_WEIGHT is above zero",
                      "m_side_slope_steeper_than_20deg": "metres where the side slope exceeds the 20 deg reference",
                      "relative_effort": "walking only, in hours of suit supply at 1200 BTU/h. Same as supply_h_walking",
                      "supply_h_walking": "supply spent walking the route",
                      "supply_h_science": "supply spent standing at the stops: science_time_min at half the flat walking rate (Pandolf's standing term)",
                      "supply_h_total": "supply_h_walking + supply_h_science. This is the figure to show, not relative_effort",
                      "supply_pct_of_suit": "supply_h_total against an 8 h suit at the reference rate"},
                  "segment_fields": {"nearest_safe_place_id": "habitat or terrain shelter closest in walking time from the segment midpoint",
                                     "time_to_nearest_safe_place_min": "walking time (fastest route) from the segment midpoint to that place",
                                     "max_time_to_nearest_safe_place_min": "worst case along the segment"},
                  "time_budget_plans": budgets,
                  "routes": routes}

    # ---------------- emergency.json
    targets = [("habitat_01", "base", base)] + [(f"shelter_{i+1:02d}", "candidate_shelter", rc) for i, rc in enumerate(shelters)]
    los_walk = np.flatnonzero((los & walk).ravel())
    scenarios = []
    starts = sorted(stops, key=lambda s: -dist_base[s["rc"]])[:2]
    for s in starts:
        dist_here, _ = p.tree(s["rc"], 0.0)
        tg = list(targets)
        if len(los_walk):
            tg.append(("comms_nearest_los", "communication_point", p.rc(los_walk[np.argmin(dist_here[los_walk])])))
        for o2 in (1.0, 2.0):
            res = p.emergency(s["rc"], o2, tg, margin=C.EMERGENCY_MARGIN)
            opts = []
            for o in res["options"]:
                if not o.get("reachable", True):
                    opts.append({"destination_id": o["name"], "kind": o["kind"], "reachable": False})
                    continue
                nodes = o["nodes"]
                mt = X.metrics(nodes)
                d = {"destination_id": o["name"], "kind": o["kind"], "reachable": True,
                     "feasible_under_model": bool(o["feasible"]), **mt,
                     "geometry": X.geometry(nodes)}
                if o["kind"] == "communication_point":
                    d["destination"] = X.pt(p.rc(nodes[-1]))
                opts.append(d)
            scenarios.append({"id": f"emergency_{s['id']}_{int(o2)}h", "start_waypoint_id": s["id"],
                              "start": X.pt(s["rc"]), "suit_supply_left_h": o2, "reserve_fraction": C.EMERGENCY_MARGIN,
                              "usable_h": r1(res["usable_o2_h"], 2), "route_choice": "least effort (least oxygen under the model)",
                              "destinations": opts})
    emergency = {"oxygen_verified": False, "field_definitions": "same metric fields as routes.json (see routes.json field_definitions)",
                 "oxygen_model": "relative_effort in hours of suit supply at 1200 BTU/h; see route_model.json. Not validated for Mars.",
                 "comms_point_definition": f"nearest walkable cell with straight line of sight to a {C.BASE_ANTENNA_H_M} m antenna at the habitat, suit antenna {C.SUIT_ANTENNA_H_M} m (assumed heights)",
                 "frame": FRAME, "scenarios": scenarios}
    print(f"emergency {time.time()-t0:.1f}s", flush=True)

    # ---------------- map layers (PNG, north up, same bounds)
    gy, gx = np.gradient(a.z, a.dy, a.dx)
    sl = np.degrees(np.arctan(np.hypot(gx, gy)))
    asp = np.arctan2(-gx, gy)
    srad = np.radians(sl)
    hs = np.sin(np.radians(45)) * np.cos(srad) + np.cos(np.radians(45)) * np.sin(srad) * np.cos(np.radians(315) - asp)
    g8 = np.nan_to_num(np.clip(hs * 255, 0, 255)).astype(np.uint8)
    hs_rgba = np.dstack([g8, g8, g8, np.where(np.isfinite(a.z), 255, 0).astype(np.uint8)])
    save_png(os.path.join(A.out, "map_layers", "hillshade.png"), hs_rgba)
    layers = [{"id": "hillshade", "file": "map_layers/hillshade.png", "type": "basemap", "units": None,
               "legend": "shaded relief (sun azimuth 315, altitude 45)", "source": "HiRISE DTM"}]
    defs = [("elevation", a.z, None, None, "terrain", "m", "HiRISE DTM"),
            ("slope", a.slope, 0, 40, "magma_r", "deg", "HiRISE DTM, 5 m grid"),
            ("roughness", a.rough, 0, 8, "viridis", "deg (std of 1 m slope in cell)", "HiRISE DTM at 1 m"),
            ("thermal_inertia", np.where(a.ti > 0, a.ti, np.nan), 130, 400, "cividis", "J m-2 K-1 s-1/2", "THEMIS (Edwards, Zenodo 4931348)"),
            ("sky_blocked", 100 * sky, 0, 40, "plasma", "% of sky hidden", "computed from HiRISE DTM")]
    for name, arr, lo, hi, cmap, unit, src in defs:
        if lo is None:
            lo, hi = float(np.nanpercentile(arr, 1)), float(np.nanpercentile(arr, 99))
        save_png(os.path.join(A.out, "map_layers", f"{name}.png"), colorize(arr, lo, hi, cmap))
        layers.append({"id": name, "file": f"map_layers/{name}.png", "type": "overlay", "units": unit,
                       "legend": {"colormap": cmap, "min": r1(lo), "max": r1(hi)}, "source": src})
    mrgba = np.zeros((H, W, 4), np.uint8)
    for g, col in (("olivine", (220, 40, 40)), ("carbonate", (40, 180, 60)), ("clay", (30, 190, 210))):
        m = np.isin(a.mineral, list(GROUPS[g])) & (a.mconf >= 1)
        mrgba[m] = (*col, 200)
    save_png(os.path.join(A.out, "map_layers", "minerals.png"), mrgba)
    layers.append({"id": "minerals", "file": "map_layers/minerals.png", "type": "overlay", "units": None,
                   "legend": {"olivine": "red", "carbonate": "green", "clay": "cyan", "note": "probable detections, high + medium confidence"},
                   "source": CRISM_SRC})
    los_rgba = np.zeros((H, W, 4), np.uint8)
    los_rgba[los & walk] = (80, 160, 255, 90)
    save_png(os.path.join(A.out, "map_layers", "comms_line_of_sight.png"), los_rgba)
    layers.append({"id": "comms_line_of_sight", "file": "map_layers/comms_line_of_sight.png", "type": "overlay",
                   "units": None, "legend": "blue = straight line of sight to habitat antenna (assumed heights)",
                   "source": "computed from HiRISE DTM"})
    manifest = {"frame": FRAME, "crs_wkt": mission["crs_wkt"], "width_px": W, "height_px": H,
                "pixel_size_m": {"east": r1(a.dx, 3), "north": a.dy},
                "bounds": {"east_m": bounds_e, "north_m": bounds_n,
                           "lat_range": mission["study_area"]["lat_range"], "lon_range": mission["study_area"]["lon_range"]},
                "orientation": "north up; row 0 = northern edge; pixel (0,0) is the north-west corner",
                "no_data": "transparent pixels", "layers": layers}

    # ---------------- route_model.json
    model = {
        "algorithm": "Dijkstra shortest paths on an 8-connected directed grid graph (scipy.sparse.csgraph); "
                     "fastest = minimise time, easiest = minimise effort, pareto = weighted blends with non-dominated filtering; "
                     "multi-stop order by exhaustive search",
        "grid_m": a.cell,
        "speed": {"equation": "v = k * 6 * exp(-3.5 * |s + 0.05|) km/h, s = dz/dx, k chosen so v(0) = 3.6 km/h",
                  "sources": ["Tobler hiking function", "Apollo planners' 3.6 km/h walkback speed (Apollo Lunar Surface Journal)"]},
        "effort": {"equation": "rate = [1.5 + eta*(1.5 V^2 + 0.35 V G)] / [1.5 + 1.5 V0^2], G = max(grade %, 0) + SIDE_SLOPE_WEIGHT * 100 * tan(side slope), effort = time_h * rate",
                   "source": "Pandolf load-carriage equation (used by NASA for EVA traverse workload), no load",
                   "downhill": "counted as flat (team decision, conservative)",
                   "eta": f"1 + {C.ROUGH_WEIGHT}*roughness/{C.ROUGH_REF_DEG} deg + {C.SOIL_WEIGHT}*soil softness, capped at {C.ETA_MAX} (ASSUMPTION; softness from THEMIS between {C.SOFT_TI} and {C.FIRM_TI})"},
        "side_slope": {"equation": "tan(side)^2 = tan(terrain slope)^2 - tan(walking grade)^2",
                       "measured": "reported on every route and segment as max_side_slope_deg and m_side_slope_steeper_than_20deg",
                       "priced": f"SIDE_SLOPE_WEIGHT = {C.SIDE_SLOPE_WEIGHT} (ASSUMPTION). 0 measures without pricing. Neither Tobler nor Pandolf models side slope: both were measured walking straight up or down, and no measurement exists for a suited astronaut traversing a Martian hillside",
                       "status": "measurement is geometry and carries no assumption; the weight is ours and the README reports what values of it would change"},
        "standing": {"rate": "0.5 of the flat walking rate, from Pandolf with V = 0, which leaves only the standing term",
                     "used_for": "supply_h_science, the supply spent at science stops",
                     "status": "a lower bound: sampling and handling tools cost more than standing still"},
        "oxygen": {"unit": "hours of suit supply at 1200 BTU/h", "basis": "advanced EMU sized for 8 h at 1200 BTU/h; NASA plans planetary EVAs at 1200 BTU/h",
                   "verified_for_mars": False,
                   "gravity_note": "Speed and effort references are lunar/Earth; they over-estimate uphill effort in Mars gravity (conservative)."},
        "radiation": {"equation": "dose_uGy = sum over steps of walking_time_h x R x (1 - sky_hidden_fraction); walking only, time at stops not included",
                      "R": "median RTG-corrected dose rate (silicon) from Curiosity RAD, last 30 days of data, in uGy/h",
                      "sky_hidden_fraction": "geometric horizon proxy from the HiRISE DTM (500 m, 16 directions)",
                      "status": "ASSUMPTION / estimate: R is measured in Gale crater, not Jezero; terrain shielding of galactic cosmic rays is "
                                "approximated as proportional to the hidden sky; ground albedo, altitude and solar events are ignored. "
                                "Use for comparing routes and shelters, not as a dose prediction.",
                      "sources": ["MSL RAD Level 2, NASA CDAWeb", "Ehresmann et al. 2021; Guo et al. 2026 (terrain reduces surface dose)"]},
        "constraints": {"forbidden": ["no elevation data", "thermal inertia < 100"],
                        "warnings_only": ["slope > 20 deg (NASA Artemis suit reference)"]},
    }

    # ---------------- conditions.json (radiation)
    cond = {"radiation": rad}
    if cond["radiation"]:
        cond["radiation"]["median_uGy_per_hour"] = r1(cond["radiation"]["median_uGy_per_day"] / 24.0, 2)
    cond["weather"] = None
    if A.meda and os.path.exists(A.meda):
        days = json.load(open(A.meda))
        cond["weather"] = {
            "pressure": {"unit": "Pa", "per_sol": days,
                         "note": "Statistics of all valid samples of each sol. Hourly medians are by Local True Solar Time hour. "
                                 "Sol 417 covers only part of the day (LTST 00 and 12-23 h).",
                         "location": "Jezero crater (Perseverance MEDA), measured at the rover position on that sol",
                         "source": "MEDA PS derived data, PDS Atmospheres Node, https://atmos.nmsu.edu/PDS/data/PDS4/Mars2020/mars2020_meda/data_derived_env/ (Rodriguez-Manfredi et al. 2021, DOI 10.17189/1522849)"},
            "wind": None}
        for w in wps:
            for d in days:
                if w["id"] in d["linked_waypoints"]:
                    w["pressure_pa"] = {"sol": d["sol"], **d["pressure_pa"]}
    cond["weather_note"] = ("Pressure: MEDA PS derived files for sols 417, 420, 435, 674 and 708 (same sols as the stop photos) "
                            "selected by Ronald. Wind: not shown. MEDA has no published wind data (DER_WS) "
                            "after sol 315 (PDS Atmospheres Node, data_derived_env).")

    for name, obj in [("mission_config.json", mission), ("waypoints.json", {"frame": FRAME, "waypoints": wps}),
                      ("minerals.json", {"frame": FRAME, "note": "Probable detections from orbital CRISM data, not confirmed samples.",
                                         "minerals": minerals}),
                      ("routes.json", routes_doc), ("emergency.json", emergency), ("layers_manifest.json", manifest),
                      ("route_model.json", model), ("conditions.json", cond),
                      ("rover_positions.json", {"frame": FRAME,
                        "note": ("Perseverance end-of-drive positions inside the study area (NASA Mars 2020 waypoints, "
                                 "https://mars.nasa.gov/mmgis-maps/M20/Layers/json/M20_waypoints.json; mid-drive and interpolated points removed by Ronald). "
                                 "Positions with 'photos' are where the stop photos were taken; the camera direction is not confirmed. "
                                 "lat/lon and elevation are the rover's own values; east_m/north_m are those of the grid cell."),
                        "positions": rover})]:
        with open(os.path.join(A.out, name), "w") as f:
            json.dump(obj, f, indent=1)
    print(f"done in {time.time()-t0:.1f}s: {len(wps)} waypoints, {len(minerals)} mineral patches, "
          f"{len(routes)} routes, {len(scenarios)} emergency scenarios")


if __name__ == "__main__":
    main()
