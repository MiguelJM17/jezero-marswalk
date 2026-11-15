"""Baseline for the rover-traverse comparison.

A route that stays near Perseverance's path proves nothing on its own if a
straight line from the habitat to the same stop would also stay near it. This
script computes that baseline, and the slope profile of both, so the comparison
in README.md can be read honestly.

Run:  MARSWALK_GRID=<grid5m dir> python3 docs/validation/baseline_check.py
"""
import json, os, sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
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

    T = json.load(open(os.path.join(ROOT, "base44_handoff", "rover_traverse.json")))
    R = np.array([p for f in T["features"] for p in f["geometry"]["coordinates"]], float)
    W = {x["id"]: x for x in json.load(open(os.path.join(ROOT, "base44_handoff", "waypoints.json")))["waypoints"]}
    RT = {r["id"]: r for r in json.load(open(os.path.join(ROOT, "base44_handoff", "routes.json")))["routes"]}

    def near(poly, buf=100.0):
        pts, _ = sample(poly)
        d = np.linalg.norm(pts[:, None, :] - R[None, :, :], axis=2).min(axis=1)
        return 100.0 * float(np.mean(d <= buf))

    def steep(poly):
        pts, L = sample(poly)
        v = []
        for e, n in pts:
            r, c = int(round(r0 - n / A.dy)), int(round(c0 + e / A.dx))
            if 0 <= r < S.shape[0] and 0 <= c < S.shape[1] and np.isfinite(S[r, c]):
                v.append(S[r, c])
        v = np.array(v)
        return L, float(v.max()), float(L * np.mean(v > 20))

    print(f"{'stop':14} | {'straight line':^30} | {'our fastest route':^30}")
    print(f"{'':14} | {'% <100m':>8}{'len m':>8}{'max deg':>7}{'m>20':>7} | {'% <100m':>8}{'len m':>8}{'max deg':>7}{'m>20':>7}")
    base, ours = [], []
    for s in STOPS:
        P = [[0.0, 0.0], [W[s]["east_m"], W[s]["north_m"]]]
        nb, (Lb, mb, sb) = near(P), steep(P)
        co = RT[f"route_{s}_fastest"]["geometry"]["coordinates"]
        co = co[:len(co) // 2 + 1]                      # outbound leg only
        no, (Lo, mo, so) = near(co), steep(co)
        base.append(nb); ours.append(no)
        print(f"{s:14} | {nb:7.1f}%{Lb:8.0f}{mb:7.1f}{sb:7.0f} | {no:7.1f}%{Lo:8.0f}{mo:7.1f}{so:7.0f}")
    print(f"\nmean within 100 m of the traverse: straight line {np.mean(base):.1f}%, our routes {np.mean(ours):.1f}%")


if __name__ == "__main__":
    main()
