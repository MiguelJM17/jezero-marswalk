"""Check a running Marswalk API (local or Cloud Run) against outputs/, field by field.

    python3 tools/check_live_api.py https://<URL>
    python3 tools/check_live_api.py https://<URL> --token "$(gcloud auth print-identity-token)"   # private service
    python3 tools/check_live_api.py http://localhost:8080

Only the Python standard library is used, so it runs in Cloud Shell as is.
Checks: health, the 3 mandatory checks of API_CONTRACT.md, all 28 saved routes, the
4 saved emergency scenarios, the endpoint list in /openapi.json, CORS for the app
origins, and the map-layer URLs. Exit code 0 only if everything passes.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
H = os.path.join(HERE, "..", "outputs")
STOPS = ["olivine_01", "olivine_02", "carbonate_01", "carbonate_02", "clay_01", "clay_02"]
SKIP = {"id", "type", "label", "start", "end"}
PATHS = {"/api/emergency/reachable", "/api/health", "/api/routes/easiest", "/api/routes/fastest",
         "/api/routes/mineral-target", "/api/routes/pareto", "/api/routes/time-budget", "/api/routes/via-shelter",
         "/api/scientific-destinations", "/api/terrain/layers", "/api/terrain/point"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--token", default=None, help="identity token for a private Cloud Run service")
    ap.add_argument("--origins", default="https://marseva.us,https://jolly-mars-path-pilot.base44.app",
                    help="comma-separated app origins that must pass CORS")
    A = ap.parse_args()
    base = A.url.rstrip("/")
    ok, bad = [], []

    def call(method, path, body=None, headers=None):
        h = {"Content-Type": "application/json"}
        if A.token:
            h["Authorization"] = f"Bearer {A.token}"
        h.update(headers or {})
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(base + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read()
                try:
                    j = json.loads(raw) if raw else None
                except ValueError:
                    j = raw.decode(errors="replace")[:200]
                return r.status, j, dict(r.headers)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                j = json.loads(raw)
            except Exception:
                j = raw.decode(errors="replace")[:200]
            return e.code, j, dict(e.headers)

    def check(name, cond, info=""):
        (ok if cond else bad).append(name)
        print(("PASS " if cond else "FAIL ") + name + ("" if cond or not info else f"  -> {info}"), flush=True)

    def diff(live, saved, skip=()):
        return [k for k in saved if k not in SKIP and k not in skip and live.get(k) != saved[k]]

    routes = {r["id"]: r for r in json.load(open(os.path.join(H, "routes.json")))["routes"]}
    emerg = {s["id"]: s for s in json.load(open(os.path.join(H, "emergency.json")))["scenarios"]}

    t = time.time()
    st, j, _ = call("GET", "/api/health")
    check(f"health ({time.time()-t:.1f} s, first call wakes the service)", st == 200 and j and j.get("ok") is True, j)

    st, j, _ = call("POST", "/api/routes/easiest", {"to": {"waypoint_id": "carbonate_01"}})
    x = (j or {}).get("routes", [{}])[0] if st == 200 else {}
    KEYS = ("distance_m", "time_min", "relative_effort", "max_slope_deg", "max_terrain_slope_deg")
    want = tuple(routes["route_carbonate_01_easiest"].get(k) for k in KEYS)
    got = tuple(x.get(k) for k in KEYS)
    # Read from the saved route rather than pinned here, so a deliberate change to the
    # cost model does not make the deploy check fail against its own engine.
    check(f"mandatory 1: carbonate_01 easiest matches the saved route {want}",
          got == want and j.get("oxygen_verified") is False, got)

    st, j, _ = call("POST", "/api/emergency/reachable", {"position": {"waypoint_id": "olivine_02"}, "suit_supply_left_h": 1})
    s = emerg["emergency_olivine_02_1h"]
    d = [k for k in ("start", "suit_supply_left_h", "reserve_fraction", "usable_h", "route_choice", "destinations")
         if st != 200 or j.get(k) != s[k]]
    check("mandatory 2: emergency olivine_02 1 h = emergency_olivine_02_1h", not d, d)

    st, j, _ = call("POST", "/api/routes/easiest", {"to": {"east_m": 5000, "north_m": 0}})
    check("mandatory 3: point outside the grid -> 422", st == 422 and isinstance(j, dict) and j.get("error") == "outside_grid",
          (st, j))
    st, j, _ = call("POST", "/api/routes/easiest", {"to": {"waypoint_id": "nope"}})
    check("unknown waypoint -> 404 {error, detail}", st == 404 and isinstance(j, dict) and set(j) == {"error", "detail"}, (st, j))

    # all 28 saved routes
    seen = set()
    for stop in STOPS:
        for kind in ("fastest", "easiest", "via_shelter"):
            path = "/api/routes/" + ("via-shelter" if kind == "via_shelter" else kind)
            st, j, _ = call("POST", path, {"to": {"waypoint_id": stop}})
            rid = f"route_{stop}_{kind}"
            seen.add(rid)
            dd = diff(j["routes"][0], routes[rid]) if st == 200 else [st]
            check(f"{rid}", not dd, dd)
        if f"route_{stop}_pareto" in routes:
            st, j, _ = call("POST", "/routes", {"to": {"waypoint_id": stop}})
            bal = [r for r in (j or {}).get("routes", []) if r.get("label") == "balanced"] if st == 200 else []
            rid = f"route_{stop}_pareto"
            seen.add(rid)
            dd = diff(bal[0], routes[rid]) if len(bal) == 1 else ["no single balanced route"]
            check(rid, not dd, dd)
    for bh, rid in [(1, "route_budget_1h"), (1.5, "route_budget_1_5h"), (2, "route_budget_2h"), (3, "route_budget_3h"),
                    (4, "route_budget_4h"), (6, "route_tour_all_stops")]:
        st, j, _ = call("POST", "/api/routes/time-budget", {"time_budget_min": bh * 60})
        seen.add(rid)
        dd = diff(j["best_tour"], routes[rid]) if st == 200 and j.get("best_tour") else [st]
        check(rid, not dd, dd)
    check("all 28 saved routes compared", seen == set(routes) and len(routes) == 28, sorted(set(routes) - seen))

    for sid, s in emerg.items():
        st, j, _ = call("POST", "/api/emergency/reachable",
                        {"position": {"waypoint_id": s["start_waypoint_id"]}, "suit_supply_left_h": s["suit_supply_left_h"]})
        d = [k for k in ("start", "usable_h", "destinations") if st != 200 or j.get(k) != s[k]]
        check(sid, not d and j.get("oxygen_verified") is False, d)

    st, j, _ = call("GET", "/openapi.json")
    have = set((j or {}).get("paths", {})) if st == 200 else set()
    check("openapi.json lists the 11 endpoints", PATHS <= have, sorted(PATHS - have))

    st, j, _ = call("GET", "/api/terrain/layers")
    f = j["layers"][1]["file"] if st == 200 else ""
    check("layer URLs are absolute https", f.startswith("https://") or base.startswith("http://localhost"), f)
    if f:
        req = urllib.request.Request(f, headers={"Authorization": f"Bearer {A.token}"} if A.token else {})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                check("layer PNG downloads", r.status == 200 and r.read(4) == b"\x89PNG")
        except Exception as e:
            check("layer PNG downloads", False, e)

    for origin in [o.strip() for o in A.origins.split(",") if o.strip()]:
        st, _, hd = call("OPTIONS", "/api/routes/easiest",
                         headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
        hd = {k.lower(): v for k, v in hd.items()}
        check(f"CORS allows {origin}", hd.get("access-control-allow-origin") == origin, (st, hd.get("access-control-allow-origin")))

    print(f"\n{len(ok)} passed, {len(bad)} failed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
