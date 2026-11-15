"""Export the analysis grid in the shape Mary's Base44 import page expects:
{ cell_size, bounds:{minX,minY,maxX,maxY}, elevation:[...], thermal_inertia:[...], minerals:{carbonate,olivine,clay}, crs }
in local ENU metres from the habitat, on a square grid (resampled from the 5 m grid).

python -m routing.export_grid --base-lat 18.452739 --base-lon 77.405768 --half 1400 --cell 10 --out base44_handoff/terrain_grid_10m.json
"""
import argparse
import json

import numpy as np
from scipy.ndimage import map_coordinates

from . import config as C
from .terrain import load_area

GROUPS = {"carbonate": [2], "olivine": [1], "clay": [3, 9, 10]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", default="data/processed/grid5m")
    ap.add_argument("--base-lat", type=float, required=True)
    ap.add_argument("--base-lon", type=float, required=True)
    ap.add_argument("--half", type=float, default=1400.0)
    ap.add_argument("--cell", type=float, default=10.0)
    ap.add_argument("--out", required=True)
    A = ap.parse_args()

    a = load_area(A.grid, A.base_lon, A.base_lat, A.half + 50)
    r0, c0 = a.lonlat_to_rc(A.base_lon, A.base_lat)
    n = int(round(2 * A.half / A.cell))
    # cell centres, row 0 = north
    e = -A.half + A.cell * (np.arange(n) + 0.5)
    nn = A.half - A.cell * (np.arange(n) + 0.5)
    E, N = np.meshgrid(e, nn)
    rows = r0 - N / a.dy
    cols = c0 + E / a.dx
    coords = np.vstack([rows.ravel(), cols.ravel()])

    z = np.where(np.isfinite(a.z), a.z, np.nan)
    elev = map_coordinates(np.nan_to_num(z, nan=-1e9), coords, order=1, mode="nearest").reshape(n, n)
    valid = map_coordinates(np.isfinite(z).astype(float), coords, order=1, mode="nearest").reshape(n, n) > 0.99
    slope = map_coordinates(np.nan_to_num(a.slope), coords, order=1, mode="nearest").reshape(n, n)
    rough = map_coordinates(np.nan_to_num(a.rough), coords, order=1, mode="nearest").reshape(n, n)
    ti = map_coordinates(a.ti.astype(float), coords, order=0, mode="nearest").reshape(n, n)
    mcls = map_coordinates(a.mineral.astype(float), coords, order=0, mode="nearest").reshape(n, n).astype(int)
    mconf = map_coordinates(a.mconf.astype(float), coords, order=0, mode="nearest").reshape(n, n).astype(int)

    def flat(x, nd):
        x = np.where(valid, x, np.nan).ravel()
        return [None if not np.isfinite(v) else round(float(v), nd) for v in x]

    minerals = {g: [int(c) if (k in cl) else 0 for k, c in zip(mcls.ravel(), mconf.ravel())]
                for g, cl in GROUPS.items()}
    doc = {
        "cell_size": A.cell,
        "bounds": {"minX": -A.half, "minY": -A.half, "maxX": A.half, "maxY": A.half},
        "rows": n, "cols": n,
        "layout": "row-major; row 0 is the northern edge (maxY), column 0 the western edge (minX); value i*cols+j is the cell centre "
                  "at east = minX + (j+0.5)*cell_size, north = maxY - (i+0.5)*cell_size",
        "crs": "local ENU metres from the habitat (habitat_01 = 0,0) at lat 18.452739, lon 77.405768 (planetocentric, east positive, Mars 2000 sphere R=3396190 m). Same frame as base44_handoff JSON files.",
        "elevation": flat(elev, 1),
        "slope_deg": flat(slope, 1),
        "roughness_deg": flat(rough, 2),
        "thermal_inertia": flat(np.where(ti > 0, ti, np.nan), 0),
        "minerals": minerals,
        "minerals_encoding": "0 = not detected, 1 = medium confidence, 2 = high confidence (probable detections)",
        "units": {"elevation": "m (Mars 2000 sphere)", "slope_deg": "deg", "roughness_deg": "deg (std of 1 m slope)",
                  "thermal_inertia": "J m-2 K-1 s-1/2"},
        "nodata": "null",
        "resampling": f"bilinear from the team 5 m grid (elevation, slope, roughness), nearest for thermal inertia and minerals; slope reference {C.MAX_SLOPE_DEG} deg is a warning, not a mask",
        "sources": {"elevation": "USGS Mars 2020 TRN HiRISE DTM (1 m)", "thermal_inertia": "THEMIS, Edwards et al., Zenodo 4931348",
                    "minerals": "CRISM mineral map, Parente, Itoh & Saranathan, Zenodo 5575824"},
        "note": "For drawing and for the import page only. Routes, times and effort come from routes.json and emergency.json; do not recompute them in the browser.",
    }
    with open(A.out, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
    print(n, "x", n, "valid", int(valid.sum()), "elev", float(np.nanmin(np.where(valid, elev, np.nan))), float(np.nanmax(np.where(valid, elev, np.nan))))


if __name__ == "__main__":
    main()
