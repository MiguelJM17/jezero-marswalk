"""Summarise MEDA derived pressure (PS) files: per-sol median/min/max and hourly medians (LTST).

python3 processing/meda_summary.py meda/WE__0417___________DER_PS__________________P01.CSV ... > data/meda_pressure_summary.json
Files: PDS Atmospheres Node, mars2020_meda/data_derived_env (Rodriguez-Manfredi et al. 2021, DOI 10.17189/1522849).
"""
import csv
import json
import os
import sys

import numpy as np

# sol of each stop photo -> stops (see ronald/tabla_fotos.csv)
STOPS = {417: ["olivine_01"], 420: ["olivine_02"], 435: ["clay_01"], 674: ["clay_02"], 708: ["carbonate_01", "carbonate_02"]}

out = []
for f in sys.argv[1:]:
    sol = int(os.path.basename(f)[4:8])
    P, H = [], []
    with open(f) as fh:
        for r in csv.DictReader(fh):
            try:
                p = float(r["PRESSURE"])
            except ValueError:
                continue
            if not np.isfinite(p) or p <= 0:
                continue
            P.append(p)
            H.append(int(r["LTST"].split()[1][:2]))
    P, H = np.array(P), np.array(H)
    hourly = {int(h): round(float(np.median(P[H == h])), 1) for h in np.unique(H)}
    out.append({"sol": sol, "linked_waypoints": STOPS.get(sol, []), "n_samples": int(len(P)),
                "pressure_pa": {"median": round(float(np.median(P)), 1), "min": round(float(P.min()), 1),
                                "max": round(float(P.max()), 1)},
                "ltst_hours_covered": sorted(hourly), "hourly_median_pa_by_ltst": hourly, "file": os.path.basename(f)})
json.dump(out, sys.stdout, indent=1)
