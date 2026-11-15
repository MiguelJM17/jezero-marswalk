"""Baseline for the rover-traverse comparison.

A route that stays near Perseverance's path proves nothing on its own if a
straight line from the habitat to the same stop would also stay near it. This
script computes that baseline, and the slope profile of both, so the comparison
in README.md can be read honestly. It also measures side slope, the cross-slope
component no speed or effort equation here models, on our routes and on the ground
Perseverance actually drove, as a reality check on what a real traverse accepted.

Run:  MARSWALK_GRID=<grid5m dir> python3 docs/validation/baseline_check.py
"""
import json, os, sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from routing.planner import side_slope_deg
from routing.terrain import load_area

HAB_LON, HAB_LAT = 77.405768, 18.452739
STOPS = ["clay_01", "clay_02", "carbonate_01", "carbonate_02", "olivine_01", "olivine_02"]
ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def sample(poly, step=5.0):
    P = np.asarray(poly, float)
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    L = seg.sum()
    n = max(int(L / step), 2)
    s = np.linspace(0, L, n)
    cum = np.concatenate([[0], np.cumsum(seg)])
    i = np.clip(np.searchsorted(cum, s) - 1, 0, len(seg) - 1)
    f = (s - cum[i]) / np.maximum(seg[i], 1e-9)
    return P[i] + (P[i + 1] - P[i]) * f[:, None], L


def main():
    grid = os.environ.get("MARSWALK_GRID", os.path.join(ROOT, "data", "processed", "grid5m"))
    A = load_area(grid, HAB_LON, HAB_LAT, 1500.0)
    S = A.slope if A.slope.max() > 2 else np.degrees(np.arctan(A.slope))
    r0, c0 = A.lonlat_to_rc(HAB_LON, HAB_LAT)

    T = json.load(open(os.path.join(ROOT, "outputs", "rover_traverse.json")))
    R = np.array([p for f in T["features"] for p in f["geometry"]["coordinates"]], float)
    W = {x["id"]: x for x in json.load(open(os.path.join(ROOT, "outputs", "waypoints.json")))["waypoints"]}
    RT = {r["id"]: r for r in json.load(open(os.path.join(ROOT, "outputs", "routes.json")))["routes"]}

    def near(poly, buf=100.0):
        pts, _ = sample(poly)
        d = np.linalg.norm(pts[:, None, :] - R[None, :, :], axis=2).min(axis=1)
        return 100.0 * float(np.mean(d <= buf))

    def cells(pts):
        out = []
        for e, n in pts:
            r, c = int(round(r0 - n / A.dy)), int(round(c0 + e / A.dx))
            if 0 <= r < S.shape[0] and 0 <= c < S.shape[1] and np.isfinite(S[r, c]):
                out.append((r, c))
        return out

    def steep(poly):
        pts, L = sample(poly)
        rc = cells(pts)
        v = np.array([S[r, c] for r, c in rc])
        return L, float(v.max()), float(L * np.mean(v > 20))

    def side(poly, step=5.0):
        """Side slope along a polyline, from the terrain slope and the walking grade."""
        pts, L = sample(poly, step)
        rc = cells(pts)
        if len(rc) < 2:
            return 0.0, 0.0
        terr = np.array([S[r, c] for r, c in rc])
        z = np.array([A.z[r, c] for r, c in rc])
        grade = np.diff(z) / step
        sd = side_slope_deg(0.5 * (terr[:-1] + terr[1:]), grade)
        return float(sd.max()), float(step * np.sum(sd > 20))

    print(f"{'stop':14} | {'straight line':^38} | {'our fastest route':^38}")
    print(f"{'':14} | {'% <100m':>8}{'len m':>8}{'max deg':>7}{'m>20':>6}{'side':>9} | "
          f"{'% <100m':>8}{'len m':>8}{'max deg':>7}{'m>20':>6}{'side':>9}")
    base, ours = [], []
    for s in STOPS:
        P = [[0.0, 0.0], [W[s]["east_m"], W[s]["north_m"]]]
        nb, (Lb, mb, sb) = near(P), steep(P)
        xb, _ = side(P)
        co = RT[f"route_{s}_fastest"]["geometry"]["coordinates"]
        co = co[:len(co) // 2 + 1]                      # outbound leg only
        no, (Lo, mo, so) = near(co), steep(co)
        xo, _ = side(co)
        base.append(nb); ours.append(no)
        print(f"{s:14} | {nb:7.1f}%{Lb:8.0f}{mb:7.1f}{sb:6.0f}{xb:8.1f}d | "
              f"{no:7.1f}%{Lo:8.0f}{mo:7.1f}{so:6.0f}{xo:8.1f}d")
    print(f"\nmean within 100 m of the traverse: straight line {np.mean(base):.1f}%, our routes {np.mean(ours):.1f}%")

    # What the rover itself accepted on this ground, as a reality check. Perseverance is a
    # vehicle, not a walker, so this bounds the question rather than settling it.
    inside = R[(np.abs(R[:, 0]) < 1400) & (np.abs(R[:, 1]) < 1400)]
    if len(inside) > 2:
        mx, m20 = side(inside.tolist())
        _, rmax, r20 = steep(inside.tolist())
        print(f"Perseverance's own path inside this window: max ground slope {rmax:.1f} deg, "
              f"{r20:.0f} m above 20 deg, max side slope {mx:.1f} deg, {m20:.0f} m of side slope above 20 deg")


if __name__ == "__main__":
    main()
