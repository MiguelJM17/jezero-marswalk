"""Run Miguel's export_handoff, but take the RAD summary from the saved conditions.json
(the RAD CDF files are not in data/ and CDAWeb is not reachable from here). Only for comparison."""
import json, sys, os
sys.path.insert(0, os.getcwd())
import routing.export_handoff as E
saved = json.load(open('base44_handoff/conditions.json'))['radiation']
keep = {k: v for k, v in saved.items() if k != 'median_uGy_per_hour'}
E.rad_summary = lambda *a, **k: dict(keep)
sys.argv = [sys.argv[0]] + sys.argv[1:]
E.main()
