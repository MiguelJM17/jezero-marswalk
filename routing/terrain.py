"""Load a working area from the processed grid and derive per-cell terrain fields.

Coordinates
-----------
The grid uses the DTM's equirectangular CRS (lat_ts = 0, sphere radius R read from
grid.json). Map metres east are NOT ground metres: 1 map metre east = cos(lat)
ground metres. Every distance in this module is a ground distance.
"""
import json
import math
import os
from dataclasses import dataclass

import numpy as np
import rasterio
from rasterio.windows import Window

from . import config as C

LAYERS = ["elevation", "slope", "roughness", "thermal_inertia", "mineral_class", "mineral_conf"]


@dataclass
class Area:
    z: np.ndarray            # elevation (m), NaN = no data
    slope: np.ndarray        # degrees
    rough: np.ndarray        # degrees (std of 1 m slope)
    ti: np.ndarray           # thermal inertia, 0 = no data
    mineral: np.ndarray      # class id, 0 = none
    mconf: np.ndarray        # 2 high, 1 medium, 0 none
    x0: float                # map x of the left edge of column 0
    y0: float                # map y of the top edge of row 0
    cell: float              # map cell size (m)
    R: float                 # Mars sphere radius (m)
    minerals: dict

    @property
    def shape(self):
        return self.z.shape

    @property
    def lat0(self):
        return (self.y0 - 0.5 * self.shape[0] * self.cell) / self.R

    @property
    def dx(self):  # ground metres per column
        return self.cell * math.cos(self.lat0)

    @property
    def dy(self):  # ground metres per row
        return self.cell

    # --- coordinate helpers -------------------------------------------------
    def rc_to_map(self, r, c):
        return self.x0 + (c + 0.5) * self.cell, self.y0 - (r + 0.5) * self.cell

    def map_to_rc(self, x, y):
        return int((self.y0 - y) // self.cell), int((x - self.x0) // self.cell)

    def lonlat_to_rc(self, lon, lat):
        return self.map_to_rc(math.radians(lon) * self.R, math.radians(lat) * self.R)

    def rc_to_lonlat(self, r, c):
        x, y = self.rc_to_map(r, c)
        return math.degrees(x / self.R), math.degrees(y / self.R)

    def enu(self, r, c, r0, c0):
        """Local east/north ground metres of (r, c) relative to (r0, c0)."""
        return (c - c0) * self.dx, (r0 - r) * self.dy


def load_area(grid_dir, lon, lat, half_size_m):
    """Read a square window centred on (lon, lat) with the given half size (ground m)."""
    with open(os.path.join(grid_dir, "grid.json")) as f:
        meta = json.load(f)
    R = float(meta["mars_radius_m"])
    cell = float(meta["cell_size_m"])
    t = meta["transform"]  # a, b, c, d, e, f
    gx0, gy0 = t[2], t[5]
    x, y = math.radians(lon) * R, math.radians(lat) * R
    rc, cc = int((gy0 - y) // cell), int((x - gx0) // cell)
    hr = int(math.ceil(half_size_m / cell))
    hc = int(math.ceil(half_size_m / (cell * math.cos(math.radians(lat)))))
    r0, c0 = max(0, rc - hr), max(0, cc - hc)
    r1, c1 = min(meta["height"], rc + hr + 1), min(meta["width"], cc + hc + 1)
    if r1 <= r0 or c1 <= c0:
        raise ValueError("requested point is outside the processed grid")
    win = Window(c0, r0, c1 - c0, r1 - r0)
    arrs = {}
    for n in LAYERS:
        with rasterio.open(os.path.join(grid_dir, f"{n}.tif")) as s:
            arrs[n] = s.read(1, window=win)
    return Area(
        z=arrs["elevation"].astype(np.float64),
        slope=arrs["slope"].astype(np.float64),
        rough=arrs["roughness"].astype(np.float64),
        ti=arrs["thermal_inertia"].astype(np.float64),
        mineral=arrs["mineral_class"],
        mconf=arrs["mineral_conf"],
        x0=gx0 + c0 * cell,
        y0=gy0 - r0 * cell,
        cell=cell,
        R=R,
        minerals={int(k): v for k, v in meta["minerals"].items()},
    )


def blocked_mask(a: Area):
    """Cells nobody can enter (the edge does not exist):
    1 = no elevation data, 2 = west of the DTM artefact zone (C.WEST_EDGE_LON),
    3 = thermal inertia below C.MIN_THERMAL_INERTIA (possibly not load-bearing).
    Steep slope is a warning, not a block (team decision)."""
    reason = np.zeros(a.shape, np.uint8)
    lon = np.array([a.rc_to_lonlat(0, c)[0] for c in range(a.shape[1])])
    if 17.0 < math.degrees(a.lat0) < 20.0:  # the rule belongs to the Jezero TRN mosaic only
        reason[:, (lon < C.WEST_EDGE_LON) & (lon > C.WEST_EDGE_LON - 1.0)] = 2
    reason[(a.ti > 0) & (a.ti < C.MIN_THERMAL_INERTIA)] = 3
    reason[~np.isfinite(a.z)] = 1
    return reason


def warning_flags(a: Area):
    """Per-cell warnings: bit 1 = slope above the reference limit,
    bit 2 = thermal inertia below the trafficability reference."""
    w = np.zeros(a.shape, np.uint8)
    w[np.nan_to_num(a.slope, nan=0) > C.MAX_SLOPE_DEG] |= 1
    w[(a.ti > 0) & (a.ti < C.MIN_THERMAL_INERTIA)] |= 2
    return w


def terrain_factor(a: Area):
    """Pandolf-style terrain multiplier eta >= 1 (see config for the assumption)."""
    rough = np.nan_to_num(a.rough, nan=0.0)
    soft = np.clip((C.FIRM_TI - a.ti) / (C.FIRM_TI - C.SOFT_TI), 0.0, 1.0)
    soft[a.ti <= 0] = 0.0  # unknown soil: no soil penalty applied
    eta = 1.0 + C.ROUGH_WEIGHT * rough / C.ROUGH_REF_DEG + C.SOIL_WEIGHT * soft
    return np.minimum(eta, C.ETA_MAX)


def sky_blocked_fraction(a: Area, radius_m=C.SKYVIEW_RADIUS_M, n_az=C.SKYVIEW_AZIMUTHS):
    """Fraction of the sky hidden by terrain, 1 - SVF with SVF = 1 - mean(sin h).
    A geometric proxy only: it is NOT a radiation dose."""
    z = a.z
    H, W = z.shape
    step = min(a.dx, a.dy)
    sin_sum = np.zeros_like(z)
    for k in range(n_az):
        az = 2 * math.pi * k / n_az
        hmax = np.zeros_like(z)
        d = step
        while d <= radius_m:
            dj = int(round(d * math.sin(az) / a.dx))
            di = int(round(-d * math.cos(az) / a.dy))
            if dj == 0 and di == 0:
                d += step
                continue
            dist = math.hypot(dj * a.dx, di * a.dy)
            sh = np.full_like(z, np.nan)
            ys, yd = (slice(di, H), slice(0, H - di)) if di >= 0 else (slice(0, H + di), slice(-di, H))
            xs, xd = (slice(dj, W), slice(0, W - dj)) if dj >= 0 else (slice(0, W + dj), slice(-dj, W))
            sh[yd, xd] = z[ys, xs]
            ang = np.arctan((sh - z) / dist)
            hmax = np.fmax(hmax, np.nan_to_num(ang, nan=0.0))
            d += step
        sin_sum += np.sin(np.clip(hmax, 0, None))
    blocked = sin_sum / n_az
    blocked[~np.isfinite(z)] = np.nan
    return blocked


def line_of_sight(a: Area, r0, c0, h0=C.BASE_ANTENNA_H_M, h1=C.SUIT_ANTENNA_H_M, max_m=None):
    """Boolean grid: does a straight line from the base antenna reach each cell?"""
    z = a.z
    H, W = z.shape
    rr, cc = np.mgrid[0:H, 0:W]
    ex, ny = (cc - c0) * a.dx, (r0 - rr) * a.dy
    dist = np.hypot(ex, ny)
    n = int(np.ceil(dist.max() / min(a.dx, a.dy))) + 1
    zb = z[r0, c0] + h0
    zt = z + h1
    vis = np.isfinite(z)
    for k in range(1, n):
        f = k / n
        ri = np.rint(r0 + (rr - r0) * f).astype(int)
        ci = np.rint(c0 + (cc - c0) * f).astype(int)
        zl = z[ri, ci]
        zline = zb + (zt - zb) * f
        vis &= ~(np.nan_to_num(zl, nan=-1e9) > zline)
    if max_m is not None:
        vis &= dist <= max_m
    return vis
