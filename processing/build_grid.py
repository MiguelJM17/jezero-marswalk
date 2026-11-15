"""Build the common analysis grid for the Jezero study area.

Reads the USGS Mars 2020 TRN HiRISE DTM (1 m), THEMIS thermal inertia (100 m)
and the CRISM mineral map (36 m), and writes every layer on ONE grid that shares
the DTM's CRS and origin, at a coarser cell size (default 10 m).

Layers written to data/processed/grid<R>m/:
  elevation.tif        mean elevation of the 1 m cells (m)
  slope.tif            slope from the R-m elevation grid (degrees)
  slope1m_max.tif      steepest 1 m slope inside each cell (degrees)
  roughness.tif        std of the 1 m slope inside each cell (degrees)
  valid_frac.tif       fraction of 1 m cells with data
  thermal_inertia.tif  THEMIS TI resampled bilinearly (J m-2 K-1 s-1/2), 0 = no data
  mineral_class.tif    CRISM class id (see MINERALS below), 0 = none/unknown
  mineral_conf.tif     2 = high confidence, 1 = medium, 0 = none
  hillshade.png        shaded relief for display
  grid.json            grid definition + sources

The DTM is processed in horizontal strips so it fits in ~3 GB of RAM.
Nothing is hard-coded about the CRS: it is read from the DTM file.
"""
import argparse
import json
import math
import os

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import Affine
from rasterio.warp import reproject
from rasterio.windows import Window

# CRISM legend from Jezero_readme.pdf (Parente, Itoh, Saranathan), slide 5.
# id: (name, high-confidence RGB, medium-confidence RGB)
MINERALS = {
    1: ("Olivine", (255, 0, 0), (153, 0, 0)),
    2: ("Mg-Carbonate", (0, 255, 0), (0, 153, 0)),
    3: ("Fe/Mg-Smectite", (0, 255, 255), (0, 153, 153)),
    4: ("Olivine + Smectite", (255, 128, 114), (153, 77, 68)),
    5: ("Olv. Smect + 2.2um", (128, 128, 0), (77, 77, 0)),
    6: ("Carb. + 2.2um", (255, 215, 0), (153, 129, 0)),
    7: ("High Ca. Pyroxene", (255, 128, 0), (153, 77, 0)),
    8: ("Low Ca. Pyroxene", (218, 165, 32), (130, 99, 19)),
    9: ("Kaolinite", (139, 69, 19), (83, 41, 11)),
    10: ("Mg-Smectite 2", (0, 0, 255), (0, 0, 153)),
}
COLOR_TOL = 30.0  # max RGB distance to accept a legend match (map colours are exact codes)

SOURCES = {
    "dtm": "USGS Mars 2020 TRN HiRISE DTM Mosaic, https://doi.org/10.5066/P9REJ9JN",
    "thermal_inertia": "THEMIS-derived Thermal Inertia of Jezero Crater, Mars (Edwards), https://zenodo.org/record/4931348",
    "minerals": "Map of the dominant mineralogy over and around the Mars2020 landing ellipse (Parente, Itoh, Saranathan), https://zenodo.org/record/5575824",
}


def block_reduce(a, r, func):
    h, w = a.shape
    b = a[: h - h % r, : w - w % r].reshape(h // r, r, w // r, r)
    with np.errstate(all="ignore"):
        return func(b, axis=(1, 3))


def classify_crism(rgb):
    """rgb: (3, H, W) uint8 -> (class, conf) uint8 arrays."""
    px = rgb.reshape(3, -1).T.astype(np.float32)
    cls = np.zeros(px.shape[0], np.uint8)
    conf = np.zeros(px.shape[0], np.uint8)
    best = np.full(px.shape[0], np.inf, np.float32)
    for cid, (_, hi, med) in MINERALS.items():
        for col, c in ((hi, 2), (med, 1)):
            d = np.linalg.norm(px - np.array(col, np.float32), axis=1)
            m = (d < best) & (d <= COLOR_TOL)
            cls[m], conf[m], best[m] = cid, c, d[m]
    shape = rgb.shape[1:]
    return cls.reshape(shape), conf.reshape(shape)


def write(path, arr, profile, nodata=None):
    p = dict(profile, dtype=arr.dtype.name, count=1, nodata=nodata, compress="deflate")
    with rasterio.open(path, "w", **p) as dst:
        dst.write(arr, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--res", type=int, default=10, help="cell size in metres (multiple of the 1 m DTM)")
    ap.add_argument("--strip", type=int, default=50, help="grid rows per processing strip")
    a = ap.parse_args()

    R = a.res
    dtm_path = os.path.join(a.data, "JEZ_hirise_soc_006_DTM_MOLAtopography_DeltaGeoid_1m_Eqc_latTs0_lon0_blend40.tif")
    out = os.path.join(a.data, "processed", f"grid{R}m")
    os.makedirs(out, exist_ok=True)

    with rasterio.open(dtm_path) as dtm:
        assert abs(dtm.res[0] - 1.0) < 1e-9 and abs(dtm.res[1] - 1.0) < 1e-9, "expected a 1 m DTM"
        crs, t = dtm.crs, dtm.transform
        R_MARS = float(crs.to_dict()["R"])  # sphere radius read from the file's CRS
        H, W = dtm.height // R, dtm.width // R
        gt = Affine(R, 0, t.c, 0, -R, t.f)
        nod = dtm.nodata
        elev = np.full((H, W), np.nan, np.float32)
        s1max = np.full((H, W), np.nan, np.float32)
        rough = np.full((H, W), np.nan, np.float32)
        vfrac = np.zeros((H, W), np.float32)
        for g0 in range(0, H, a.strip):
            g1 = min(H, g0 + a.strip)
            r0, r1 = g0 * R, g1 * R
            # 1-row halo so the 1 m gradient is defined at strip edges
            h0, h1 = max(0, r0 - 1), min(dtm.height, r1 + 1)
            z = dtm.read(1, window=Window(0, h0, W * R, h1 - h0)).astype(np.float32)
            z[(z < -1e30) | (z == nod)] = np.nan
            # Equirectangular (lat_ts = 0): 1 map metre east = cos(lat) ground metres.
            lat = (t.f - 0.5 * (h0 + h1)) / R_MARS
            gy, gx = np.gradient(z, 1.0, math.cos(lat))
            s = np.degrees(np.arctan(np.hypot(gx, gy))).astype(np.float32)
            z, s = z[r0 - h0 : r0 - h0 + (r1 - r0)], s[r0 - h0 : r0 - h0 + (r1 - r0)]
            valid = np.isfinite(z)
            vfrac[g0:g1] = block_reduce(valid.astype(np.float32), R, np.mean)
            elev[g0:g1] = block_reduce(z, R, np.nanmean)
            s1max[g0:g1] = block_reduce(s, R, np.nanmax)
            rough[g0:g1] = block_reduce(s, R, np.nanstd)
            print(f"rows {g1}/{H}", flush=True)

    # cells with less than half of their 1 m pixels are treated as no data
    bad = vfrac < 0.5
    for arr in (elev, s1max, rough):
        arr[bad] = np.nan
    gy, gx = np.gradient(elev, R)
    row_lat = (gt.f - (np.arange(H) + 0.5) * R) / R_MARS
    gx = gx / np.cos(row_lat)[:, None]  # map-x metres -> ground metres
    slope = np.degrees(np.arctan(np.hypot(gx, gy))).astype(np.float32)

    prof = dict(driver="GTiff", height=H, width=W, crs=crs, transform=gt)
    nan = float("nan")
    write(f"{out}/elevation.tif", elev, prof, nan)
    write(f"{out}/slope.tif", slope, prof, nan)
    write(f"{out}/slope1m_max.tif", s1max, prof, nan)
    write(f"{out}/roughness.tif", rough, prof, nan)
    write(f"{out}/valid_frac.tif", vfrac, prof)

    # THEMIS thermal inertia -> grid (bilinear); source nodata is 0
    ti = np.zeros((H, W), np.float32)
    with rasterio.open(os.path.join(a.data, "Jezero_Thermal_Inertia_v1.tiff")) as src:
        assert src.crs is not None
        reproject(rasterio.band(src, 1), ti, src_nodata=0, dst_transform=gt, dst_crs=crs,
                  dst_nodata=0, resampling=Resampling.bilinear)
    write(f"{out}/thermal_inertia.tif", ti, prof, 0)

    # CRISM colours -> class ids at native res, then mode-resample to grid
    with rasterio.open(os.path.join(a.data, "jezeroFinal.tif")) as src:
        cls, conf = classify_crism(src.read())
        mc = np.zeros((H, W), np.uint8)
        mf = np.zeros((H, W), np.uint8)
        reproject(cls, mc, src_transform=src.transform, src_crs=src.crs, src_nodata=0,
                  dst_transform=gt, dst_crs=crs, dst_nodata=0, resampling=Resampling.mode)
        reproject(conf, mf, src_transform=src.transform, src_crs=src.crs, src_nodata=0,
                  dst_transform=gt, dst_crs=crs, dst_nodata=0, resampling=Resampling.mode)
    mf[mc == 0] = 0
    write(f"{out}/mineral_class.tif", mc, prof, 0)
    write(f"{out}/mineral_conf.tif", mf, prof, 0)

    # hillshade for display (sun azimuth 315, altitude 45)
    asp = np.arctan2(-gx, gy)
    sr = np.arctan(np.hypot(gx, gy))
    az, alt = math.radians(315), math.radians(45)
    hs = np.sin(alt) * np.cos(sr) + np.cos(alt) * np.sin(sr) * np.cos(az - asp)
    img = np.nan_to_num(np.clip(hs * 255, 0, 255), nan=0.0)
    img[~np.isfinite(elev)] = 0
    try:
        from PIL import Image
        Image.fromarray(img.astype(np.uint8)).save(f"{out}/hillshade.png")
    except ImportError:
        import matplotlib.pyplot as plt
        plt.imsave(f"{out}/hillshade.png", img.astype(np.uint8), cmap="gray", vmin=0, vmax=255)

    meta = {
        "cell_size_m": R,
        "width": W,
        "height": H,
        "crs_wkt": crs.to_wkt(),
        "transform": list(gt)[:6],
        "note": "x = easting (m), y = northing (m); lon_deg = degrees(x / R_mars), lat_deg = degrees(y / R_mars) for this equirectangular CRS",
        "mars_radius_m": crs.to_dict().get("R"),
        "minerals": {k: v[0] for k, v in MINERALS.items()},
        "sources": SOURCES,
    }
    with open(f"{out}/grid.json", "w") as f:
        json.dump(meta, f, indent=2)

    fin = np.isfinite(elev)
    print(json.dumps({
        "grid": [H, W],
        "valid_cells": int(fin.sum()),
        "elev_min_max": [float(np.nanmin(elev)), float(np.nanmax(elev))],
        "slope_p50_p99": [float(np.nanpercentile(slope, 50)), float(np.nanpercentile(slope, 99))],
        "ti_range_on_valid": [float(ti[fin & (ti > 0)].min()), float(ti[fin & (ti > 0)].max())],
        "mineral_cells": {MINERALS[k][0]: int((mc[fin] == k).sum()) for k in MINERALS},
    }, indent=1))


if __name__ == "__main__":
    main()
