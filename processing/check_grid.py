"""Render a quick-look figure of every grid layer (for checking, not for users)."""
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio

d = sys.argv[1] if len(sys.argv) > 1 else "data/processed/grid10m"
out = sys.argv[2] if len(sys.argv) > 2 else "checks/grid_layers.png"
names = ["elevation", "slope", "slope1m_max", "roughness", "thermal_inertia", "mineral_class"]
fig, ax = plt.subplots(2, 3, figsize=(18, 12))
for a, n in zip(ax.ravel(), names):
    with rasterio.open(f"{d}/{n}.tif") as s:
        x = s.read(1).astype(float)
        if s.nodata is not None and not np.isnan(s.nodata):
            x[x == s.nodata] = np.nan
    if n == "mineral_class":
        im = a.imshow(np.where(x > 0, x, np.nan), cmap="tab10", vmin=1, vmax=10, interpolation="nearest")
    else:
        lo, hi = np.nanpercentile(x, [1, 99])
        im = a.imshow(x, cmap="viridis", vmin=lo, vmax=hi)
    a.set_title(n)
    a.axis("off")
    fig.colorbar(im, ax=a, fraction=0.04)
plt.tight_layout()
plt.savefig(out, dpi=60)
print("saved", out)
