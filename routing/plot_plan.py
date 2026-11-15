"""Check figure: plan routes, stops, shelters and emergency paths over the real terrain."""
import json
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .terrain import load_area

plan_path = sys.argv[1]
out = sys.argv[2]
grid = sys.argv[3] if len(sys.argv) > 3 else "data/processed/grid5m"
p = json.load(open(plan_path))
b = p["base"]
a = load_area(grid, b["lon"], b["lat"], 1000.0)
base_rc = a.lonlat_to_rc(b["lon"], b["lat"])
H, W = a.shape
ext = [(0 - base_rc[1] - 0.5) * a.dx, (W - base_rc[1] - 0.5) * a.dx,
       (base_rc[0] - H + 0.5) * a.dy, (base_rc[0] + 0.5) * a.dy]
gy, gx = np.gradient(a.z, a.dy, a.dx)
slope = np.degrees(np.arctan(np.hypot(gx, gy)))
asp = np.arctan2(-gx, gy)
sr = np.radians(slope)
hs = np.sin(np.radians(45)) * np.cos(sr) + np.cos(np.radians(45)) * np.sin(sr) * np.cos(np.radians(315) - asp)

fig, ax = plt.subplots(1, 2, figsize=(20, 10))
for k, axx in enumerate(ax):
    axx.imshow(hs, cmap="gray", extent=ext)
    if k == 1:
        im = axx.imshow(np.where(slope > 20, slope, np.nan), cmap="autumn_r", extent=ext, alpha=0.7, vmin=20, vmax=40)
        fig.colorbar(im, ax=axx, fraction=0.04, label="slope > 20 deg (5 m grid)")
    cols = {"preferred (least effort)": "tab:green", "fastest": "tab:red", "balanced": "tab:orange"}
    for r in p["routes"]:
        for o in r["options"]:
            pts = np.array(o["path"])
            axx.plot(pts[:, 2], pts[:, 3], color=cols.get(o["label"], "tab:blue"), lw=2 if o.get("preferred") else 1,
                     alpha=0.9)
    for s in p["stops"]:
        axx.plot(s["east_m"], s["north_m"], "o", ms=10, mec="k", color="cyan")
        axx.annotate(s["name"], (s["east_m"], s["north_m"]), xytext=(6, 6), textcoords="offset points", color="cyan", fontsize=9)
    for s in p["shelters"]:
        axx.plot(s["east_m"], s["north_m"], "^", ms=9, mec="k", color="yellow")
        axx.annotate(f"{s['name']} {s['sky_blocked_pct']}%", (s["east_m"], s["north_m"]), xytext=(6, -10),
                     textcoords="offset points", color="yellow", fontsize=8)
    axx.plot(0, 0, "*", ms=18, color="white", mec="k")
    axx.set_xlabel("east of habitat (m)")
    axx.set_ylabel("north of habitat (m)")
ax[0].set_title("Routes: green = least effort, red = fastest, orange = balanced")
ax[1].set_title("Same, over terrain steeper than 20 deg")
plt.tight_layout()
plt.savefig(out, dpi=70)
print("saved", out)
