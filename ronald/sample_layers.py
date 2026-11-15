"""
Sample the team's 10 m layers (mineral class, mineral confidence, DTM coverage)
and, optionally, the full DTM at rover positions.

Usage:
    python sample_layers.py --points <csv with lat, lon> \
        --class mineral_class.tif --conf mineral_conf.tif --valid valid_frac.tif \
        [--grid grid.json] [--dtm <dtm.tif>] [--radius 1] --out <out.csv>

Coordinates: lat/lon in degrees, planetocentric latitude, east-positive
longitude (same convention as the NASA waypoints file and the team grid,
Mars 2000 sphere R = 3,396,190 m).

Columns added:
    class_point           mineral class at the point (0 = none)
    mineral_point         its name (from grid.json "minerals")
    conf_point            confidence at the point (2 high, 1 medium, 0 none)
    hi_<group>_cells      number of cells in the (2r+1)x(2r+1) window with
                          high confidence (conf == 2) and a class of that group
    valid_frac            DTM coverage fraction of the cell (>= 0.5 = inside)
    dtm_elev_m            DTM elevation (only with --dtm)
    dtm_minus_rover_m     dtm_elev_m - elev_geoid_m (only with --dtm)

Groups (pure classes only; mixtures 4, 5, 6 are reported in class_point
but not counted in any group):
    olivine   = {1}
    carbonate = {2}
    clay      = {3, 9, 10}   (Fe/Mg-smectite, kaolinite, Mg-smectite 2)
"""
import argparse
import csv
import json

import numpy as np
import rasterio
from pyproj import CRS
from rasterio.warp import transform
from rasterio.windows import Window

GROUPS = {"olivine": {1}, "carbonate": {2}, "clay": {3, 9, 10}}


def open_single_band(path):
    src = rasterio.open(path)
    if src.count != 1:
        raise SystemExit(
            f"{path} has {src.count} bands. This script needs a 1-band class "
            "raster (e.g. mineral_class.tif), not the RGB CRISM image.")
    return src


def to_rowcol(src, lons, lats):
    geo = CRS.from_user_input(src.crs).geodetic_crs
    xs, ys = transform(rasterio.crs.CRS.from_wkt(geo.to_wkt()), src.crs, lons, lats)
    return [src.index(x, y) for x, y in zip(xs, ys)]


def window(src, r, c, radius):
    r0, c0 = max(r - radius, 0), max(c - radius, 0)
    r1, c1 = min(r + radius + 1, src.height), min(c + radius + 1, src.width)
    if r1 <= r0 or c1 <= c0:
        return None
    return src.read(1, window=Window(c0, r0, c1 - c0, r1 - r0))


def point(src, r, c):
    if not (0 <= r < src.height and 0 <= c < src.width):
        return None
    return src.read(1, window=Window(c, r, 1, 1))[0, 0].item()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", required=True)
    ap.add_argument("--class", dest="cls", required=True)
    ap.add_argument("--conf", required=True)
    ap.add_argument("--valid", required=True)
    ap.add_argument("--grid")
    ap.add_argument("--dtm")
    ap.add_argument("--radius", type=int, default=1, help="window radius in cells (1 -> 3x3 = 30 m at 10 m)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    names = {}
    if a.grid:
        names = {int(k): v for k, v in json.load(open(a.grid))["minerals"].items()}
        names[0] = "none"

    rows = list(csv.DictReader(open(a.points, newline="", encoding="utf-8")))
    lons = [float(r["lon"]) for r in rows]
    lats = [float(r["lat"]) for r in rows]

    cls, conf, valid = open_single_band(a.cls), open_single_band(a.conf), open_single_band(a.valid)
    for s in (conf, valid):
        if s.transform != cls.transform or s.crs != cls.crs or s.shape != cls.shape:
            raise SystemExit("Layers are not on the same grid.")
    print("Grid CRS geographic datum:", CRS.from_user_input(cls.crs).geodetic_crs.name)

    for row, (r, c) in zip(rows, to_rowcol(cls, lons, lats)):
        k = point(cls, r, c)
        row["class_point"] = k
        row["mineral_point"] = names.get(k, "") if k is not None else ""
        row["conf_point"] = point(conf, r, c)
        v = point(valid, r, c)
        row["valid_frac"] = None if v is None else round(v, 3)
        wc, wf = window(cls, r, c, a.radius), window(conf, r, c, a.radius)
        for g, members in GROUPS.items():
            row[f"hi_{g}_cells"] = 0 if wc is None else int((np.isin(wc, list(members)) & (wf == 2)).sum())

    if a.dtm:
        with rasterio.open(a.dtm) as dtm:
            for row, (r, c) in zip(rows, to_rowcol(dtm, lons, lats)):
                z = point(dtm, r, c)
                if z is not None and (dtm.nodata is not None and z == dtm.nodata or np.isnan(z)):
                    z = None
                row["dtm_elev_m"] = None if z is None else round(z, 1)
                row["dtm_minus_rover_m"] = (round(z - float(row["elev_geoid_m"]), 1)
                                            if z is not None and row.get("elev_geoid_m") else None)
        d = np.array([r["dtm_minus_rover_m"] for r in rows
                      if r["dtm_minus_rover_m"] is not None and (r["valid_frac"] or 0) >= 0.5])
        if d.size:
            print(f"DTM - rover elevation, {d.size} points inside DTM: median {np.median(d):.1f} m, "
                  f"p10 {np.percentile(d, 10):.1f}, p90 {np.percentile(d, 90):.1f}, "
                  f"spread p90-p10 {np.percentile(d, 90) - np.percentile(d, 10):.1f} m")

    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("Wrote", a.out, "rows:", len(rows))


if __name__ == "__main__":
    main()
