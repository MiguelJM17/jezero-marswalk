"""Summarise MSL/RAD dose rate for the conditions panel and route dose estimates.

Uses DOSIMETRY_TOTAL column "RTG Corrected Dose B" (uGy/day, as labelled in the
files) and drops records flagged in FLAGGED_DATA. Measured by Curiosity in Gale
crater, not Jezero: every output says so.
Source: NASA CDAWeb MSL_RAD_OBS-L2, https://cdaweb.gsfc.nasa.gov/sp_phys/data/msl/rad/cdf/obs-l2/
"""
import glob
import json
import sys

import cdflib
import numpy as np

src = sys.argv[1] if len(sys.argv) > 1 else "data/rad"
out = sys.argv[2] if len(sys.argv) > 2 else "data/processed/rad_summary.json"
days = int(sys.argv[3]) if len(sys.argv) > 3 else 30

T, D, F = [], [], []
for f in sorted(glob.glob(f"{src}/*.cdf")):
    c = cdflib.CDF(f)
    labels = [str(x) for x in c.varget("DOSIMETRY_OBS_LABEL")]
    col = labels.index("RTG Corrected Dose B")
    T += list(np.atleast_1d(c.varget("EPOCH")).astype(np.int64))
    D += list(np.atleast_2d(c.varget("DOSIMETRY_TOTAL"))[:, col])
    F += [str(x).strip() for x in np.atleast_1d(c.varget("FLAGGED_DATA"))]
T, D, F = np.array(T), np.array(D, float), np.array(F)
good = (F == "") & np.isfinite(D) & (D > 0)
dates = np.array([s[:10] for s in cdflib.cdfepoch.encode(T)])
ud = np.unique(dates[good])
daily = {d: float(np.median(D[good & (dates == d)])) for d in ud}
recent = ud[-days:]
rate = float(np.median([daily[d] for d in recent]))
summary = {
    "quantity": "RTG Corrected Dose B (dose rate, silicon detector)",
    "units": "uGy/day",
    "recent_window_days": len(recent),
    "recent_from": str(recent[0]),
    "recent_to": str(recent[-1]),
    "recent_median_uGy_per_day": round(rate, 1),
    "recent_median_uGy_per_hour": round(rate / 24.0, 2),
    "year_daily_median_min_max": [round(min(daily.values()), 1), round(max(daily.values()), 1)],
    "location": "Gale crater (Curiosity rover) - not measured at Jezero",
    "flagged_records_removed": int((~good).sum()),
    "source": "NASA CDAWeb MSL_RAD_OBS-L2 (MSL/RAD)",
    "daily_median": daily,
}
json.dump(summary, open(out, "w"), indent=1)
print({k: v for k, v in summary.items() if k != "daily_median"})
