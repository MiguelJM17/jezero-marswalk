"""Build an EVA plan for a base and a list of science stops; write JSON for the app.

Usage:
  python -m routing.run_plan --grid data/processed/grid5m \
      --base-lon 77.4508 --base-lat 18.4447 --base-name "Octavia E. Butler Landing" \
      --stops curated/proposed_stops.csv --option A \
      --rad data/processed/rad_summary.json --out data/processed/plan.json

Every route carries a "card" (like a maps app): distance, time, effort, estimated
radiation dose, climb/descent, steepest grade, metres above the slope reference,
terrain, nearest-shelter distance, comms coverage, minerals crossed, and warnings.
Nothing is banned except cells without elevation data (team decision).
"""
import argparse
import csv
import json
import math
import time

import numpy as np
from scipy.ndimage import distance_transform_edt

from . import config as C
from .planner import Planner
from .terrain import line_of_sight, load_area, sky_blocked_fraction

SUIT_O2_H = C.EVA_MAX_H  # suit supply at the reference rate (8 h @ 1200 BTU/h)


def haversine(lat1, lon1, lat2, lon2, R):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def spaced_best(score, mask, k, min_sep_cells):
    s = np.where(mask, score, np.inf).ravel()
    W = mask.shape[1]
    picks = []
    for i in np.argsort(s):
        if not np.isfinite(s[i]) or len(picks) == k:
            break
        r, c = divmod(int(i), W)
        if all(math.hypot(r - pr, c - pc) >= min_sep_cells for pr, pc in picks):
            picks.append((r, c))
    return picks


class Builder:
    def __init__(self, p, base, los, shelter_dist_m, rad):
        self.p, self.a, self.base = p, p.a, base
        self.los, self.shelter_dist, self.rad = los, shelter_dist_m, rad

    def point(self, rc, **extra):
        lon, lat = self.a.rc_to_lonlat(*rc)
        e, n = self.a.enu(rc[0], rc[1], *self.base)
        return {"lon": round(lon, 6), "lat": round(lat, 6), "east_m": round(e, 1), "north_m": round(n, 1),
                "elev_m": round(float(self.a.z[rc]), 1), **extra}

    def card(self, nodes, **extra):
        p, a = self.p, self.a
        st = p.stats(nodes)
        rc = np.array([divmod(int(i), p.W) for i in nodes])
        names = a.minerals
        cls = a.mineral[rc[:, 0], rc[:, 1]]
        conf = a.mconf[rc[:, 0], rc[:, 1]]
        crossed = sorted({names.get(int(k), str(k)) for k in np.unique(cls[(cls > 0) & (conf == 2)])})
        end = rc[-1]
        dist_from_base = math.hypot((end[1] - self.base[1]) * a.dx, (self.base[0] - end[0]) * a.dy)
        card = {
            **extra,
            "distance_m": round(st["distance_m"], 1),
            "time_h": round(st["time_h"], 3),
            "effort_h": round(st["effort_o2_h"], 3),
            "effort_pct_of_suit": round(100 * st["effort_o2_h"] / SUIT_O2_H, 1),
            "radiation_uGy_est": round(st["time_h"] * self.rad["recent_median_uGy_per_hour"], 1) if self.rad else None,
            "climb_m": round(st["climb_m"], 1),
            "descent_m": round(st["descent_m"], 1),
            "max_grade_deg": round(st["max_grade_deg"], 1),
            "m_above_slope_limit": round(st["m_above_slope_limit"], 1),
            "m_soft_soil": round(st["m_soft_soil_warning"], 1),
            "mean_roughness_deg": round(st["mean_roughness_deg"], 2),
            "mean_thermal_inertia": round(st["mean_thermal_inertia"], 0),
            "max_dist_to_shelter_m": round(float(self.shelter_dist[rc[:, 0], rc[:, 1]].max()), 0),
            "comms_los_pct": round(100 * float(self.los[rc[:, 0], rc[:, 1]].mean()), 1),
            "minerals_crossed_high_conf": crossed,
        }
        warn = []
        if card["m_above_slope_limit"] > 0:
            warn.append(f"{card['m_above_slope_limit']:.0f} m steeper than {C.MAX_SLOPE_DEG:.0f} deg (NASA Artemis suit reference)")
        if card["m_soft_soil"] > 0:
            warn.append(f"{card['m_soft_soil']:.0f} m on thermal inertia < {C.MIN_THERMAL_INERTIA:.0f} (possible loose material)")
        if dist_from_base > C.OPERATING_RADIUS_M:
            warn.append(f"ends {dist_from_base:.0f} m from base, beyond the {C.OPERATING_RADIUS_M:.0f} m reference radius")
        card["warnings"] = warn
        card["path"] = p.polyline(nodes, self.base)
        return card


def read_stops(path, option):
    stops = []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        if r.get("opcion", option) != option or r.get("grupo") == "habitat":
            continue
        stops.append({"lat": float(r["lat"]), "lon": float(r["lon"]), "group": r.get("grupo", ""),
                      "mineral": r.get("mineral", ""),
                      "photo": {"sol_from": r.get("foto_sol_desde"), "sol_to": r.get("foto_sol_hasta"),
                                "rover_site_drive": r.get("foto_rmc_site_drive"),
                                "distance_photo_to_stop_m": r.get("dist_foto_a_parada_m")}})
    counts = {}
    for s in stops:
        counts[s["group"]] = counts.get(s["group"], 0) + 1
        s["name"] = f"{s['group'].capitalize()} {counts[s['group']]}"
    return stops


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", default="data/processed/grid5m")
    ap.add_argument("--base-lon", type=float, required=True)
    ap.add_argument("--base-lat", type=float, required=True)
    ap.add_argument("--base-name", default="Base")
    ap.add_argument("--base-source", default="")
    ap.add_argument("--stops", required=True)
    ap.add_argument("--option", default="A")
    ap.add_argument("--rad")
    ap.add_argument("--budget-h", type=float, default=C.EVA_MAX_H)
    ap.add_argument("--dwell-min", type=float, default=C.DEFAULT_DWELL_MIN)
    ap.add_argument("--o2-left", type=float, default=2.0)
    ap.add_argument("--skyview-m", type=float, default=500.0)
    ap.add_argument("--out", default="data/processed/plan.json")
    A = ap.parse_args()
    t0 = time.time()
    rad = json.load(open(A.rad)) if A.rad else None

    stops = read_stops(A.stops, A.option)
    R = 3396190.0
    far = max(haversine(A.base_lat, A.base_lon, s["lat"], s["lon"], R) for s in stops)
    a = load_area(A.grid, A.base_lon, A.base_lat, far + 600.0)
    p = Planner(a)
    base = a.lonlat_to_rc(A.base_lon, A.base_lat)
    if not p.walkable(base):
        raise SystemExit("base cell has no elevation data")
    for s in stops:
        s["rc"] = a.lonlat_to_rc(s["lon"], s["lat"])
    print(f"area {a.shape}, {len(p.t)} edges, farthest stop {far:.0f} m, {time.time()-t0:.1f}s", flush=True)

    sky = sky_blocked_fraction(a, radius_m=A.skyview_m)
    walk = p.block == 0
    H, W = a.shape
    rr, cc = np.mgrid[0:H, 0:W]
    near = np.hypot((cc - base[1]) * a.dx, (base[0] - rr) * a.dy) <= far + 300
    shelter_rc = spaced_best(-np.nan_to_num(sky, nan=-1), walk & near, 6, int(200 / a.cell))
    sh_mask = np.ones(a.shape, bool)
    for rc in shelter_rc:
        sh_mask[rc] = False
    shelter_dist = distance_transform_edt(sh_mask, sampling=(a.dy, a.dx))
    los = line_of_sight(a, *base)
    print(f"sky + LOS {time.time()-t0:.1f}s", flush=True)
    B = Builder(p, base, los, shelter_dist, rad)

    routes = []
    for s in stops:
        alts = p.alternatives(base, s["rc"], weights=(1.0, 0.5, 0.0))
        routes.append({"from": A.base_name, "to": s["name"],
                       "options": [B.card(al["nodes"], label=al["label"], preferred=al["preferred"]) for al in alts]})
        print(f"routes to {s['name']} {time.time()-t0:.1f}s", flush=True)

    tour = p.best_tour(base, [s["rc"] for s in stops], 0.0, A.dwell_min / 60.0, A.budget_h)
    tour_json = None
    if tour:
        names = [A.base_name] + [s["name"] for s in stops]
        legs = [B.card(nodes, frm=names[tour["order"][i]], to=names[tour["order"][i + 1]])
                for i, nodes in enumerate(tour["paths"])]
        tot_t = sum(l["time_h"] for l in legs)
        tour_json = {
            "order": [names[i] for i in tour["order"]],
            "walking_time_h": round(tot_t, 3),
            "dwell_min_per_stop": A.dwell_min,
            "total_time_h": round(tot_t + A.dwell_min / 60.0 * (len(tour["order"]) - 2), 3),
            "distance_m": round(sum(l["distance_m"] for l in legs), 1),
            "effort_h_walking": round(sum(l["effort_h"] for l in legs), 3),
            "radiation_uGy_est_total": round((tot_t + A.dwell_min / 60.0 * (len(tour["order"]) - 2)) *
                                             rad["recent_median_uGy_per_hour"], 1) if rad else None,
            "within_nominal_6h": tot_t + A.dwell_min / 60.0 * (len(tour["order"]) - 2) <= C.EVA_NOMINAL_H,
            "legs": legs,
        }
    print(f"tour {time.time()-t0:.1f}s", flush=True)

    # emergency demo: at the farthest stop with a given oxygen reserve
    fs = max(stops, key=lambda s: haversine(A.base_lat, A.base_lon, s["lat"], s["lon"], R))
    dist_here, _ = p.tree(fs["rc"], 0.0)
    targets = [(A.base_name, "base", base)]
    targets += [(f"Shelter {chr(65+i)}", "shelter", rc) for i, rc in enumerate(shelter_rc)]
    los_cells = np.flatnonzero((los & walk).ravel())
    if len(los_cells):
        targets.append(("Nearest point with line of sight to base antenna", "comms",
                        p.rc(los_cells[np.argmin(dist_here[los_cells])])))
    em = p.emergency(fs["rc"], A.o2_left, targets)
    opts = []
    for o in em["options"]:
        nodes = o.pop("nodes", None)
        if nodes:
            c = B.card(nodes, name=o["name"], kind=o["kind"], feasible=o["feasible"])
            opts.append(c)
        else:
            opts.append({"name": o["name"], "kind": o["kind"], "reachable": False})

    plan = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "frame": "east_m / north_m are ground metres from the base (local ENU); lon/lat planetocentric, east-positive",
        "base": B.point(base, name=A.base_name, source=A.base_source),
        "grid": {"cell_m": a.cell, "ground_dx_m": round(a.dx, 3), "ground_dy_m": a.dy, "rows": H, "cols": W},
        "reference_limits": {"slope_deg": C.MAX_SLOPE_DEG, "eva_nominal_h": C.EVA_NOMINAL_H,
                             "eva_max_h": C.EVA_MAX_H, "radius_m": C.OPERATING_RADIUS_M,
                             "thermal_inertia_min": C.MIN_THERMAL_INERTIA,
                             "note": "references for warnings, not bans (team decision)"},
        "units": {"effort_h": "physical effort, expressed as hours of suit supply at the reference rate of 1200 BTU/h (model); effort_pct_of_suit = effort_h / 8 h",
                  "radiation_uGy_est": "time x recent median dose rate measured by Curiosity RAD in Gale crater, not at Jezero"},
        "radiation_source": {k: v for k, v in rad.items() if k != "daily_median"} if rad else None,
        "stops": [B.point(s["rc"], **{k: v for k, v in s.items() if k not in ("rc", "lat", "lon")}) for s in stops],
        "routes": routes,
        "tour": tour_json,
        "shelters": [B.point(rc, name=f"Shelter {chr(65+i)}", sky_blocked_pct=round(100 * float(sky[rc]), 1))
                     for i, rc in enumerate(shelter_rc)],
        "emergency_demo": {"from": fs["name"], "suit_supply_left_h": A.o2_left, "margin": em["margin"],
                           "usable_h": round(em["usable_o2_h"], 3), "options": opts},
        "notes": ["Shelter value is the fraction of sky hidden by terrain (geometry), not a dose reduction.",
                  "Speed/effort models come from lunar (Apollo/Artemis) and Earth (Tobler, Pandolf) references; "
                  "they over-estimate uphill effort in Mars gravity (conservative)."],
    }
    with open(A.out, "w") as f:
        json.dump(plan, f, indent=1)
    print(f"wrote {A.out} in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
