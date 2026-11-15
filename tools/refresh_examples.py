"""Rebuild api/examples/*.json by replaying each file's own recorded request.

Every example stores the request that produced it, so refreshing them after a change
to the cost model needs no list of endpoints here: each file says what to ask for.

Run from the repository root, with the grid in place:
    MARSWALK_GRID=<grid5m dir> python3 tools/refresh_examples.py
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

EX = os.path.join(os.path.dirname(__file__), "..", "api", "examples")


def main():
    changed = []
    with TestClient(app) as c:
        for path in sorted(glob.glob(os.path.join(EX, "*.json"))):
            doc = json.load(open(path))
            req = doc["request"]
            r = c.request(req["method"], req["path"], params=req.get("query"), json=req.get("body"))
            new = {"request": req, "status": r.status_code, "response": r.json()}
            if new != doc:
                with open(path, "w") as f:
                    json.dump(new, f, indent=1)
                changed.append(os.path.basename(path))
            print(f"{os.path.basename(path):34s} {req['method']:5s} {req['path']:32s} -> {r.status_code}")
    print(f"\n{len(changed)} example(s) updated" + (": " + ", ".join(changed) if changed else ""))


if __name__ == "__main__":
    main()
