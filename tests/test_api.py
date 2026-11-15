"""API tests against the 28-route handoff (outputs/). Real Jezero data."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

H = os.path.join(os.path.dirname(__file__), "..", "outputs")
ROUTES = {r["id"]: r for r in json.load(open(os.path.join(H, "routes.json")))["routes"]}
EMERG = {s["id"]: s for s in json.load(open(os.path.join(H, "emergency.json")))["scenarios"]}
STOPS = ["olivine_01", "olivine_02", "carbonate_01", "carbonate_02", "clay_01", "clay_02"]
SKIP = {"id", "type", "label", "start", "end"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def same(live, saved, skip=()):
    diff = [k for k in saved if k not in SKIP and k not in skip and live.get(k) != saved[k]]
    assert not diff, {k: (live.get(k) if k not in ("geometry", "lonlat", "segments") else "...", saved[k]
                          if k not in ("geometry", "lonlat", "segments") else "...") for k in diff}


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "grid": "grid5m_jezero_crop", "habitat": {"lat": 18.452739, "lon": 77.405768}}


def test_mandatory_1_easiest_carbonate_01(client):
    r = client.post("/api/routes/easiest", json={"to": {"waypoint_id": "carbonate_01"}})
    assert r.status_code == 200
    j = r.json()
    assert j["oxygen_verified"] is False
    x = j["routes"][0]
    assert (x["distance_m"], x["time_min"], x["relative_effort"], x["max_slope_deg"], x["max_terrain_slope_deg"]) == \
        (1162.7, 29.3, 0.77, 27.1, 33.9)
    same(x, ROUTES["route_carbonate_01_easiest"])


@pytest.mark.parametrize("stop", STOPS)
def test_fastest_easiest_match_handoff(client, stop):
    for kind in ("fastest", "easiest"):
        x = client.post(f"/api/routes/{kind}", json={"to": {"waypoint_id": stop}}).json()["routes"][0]
        same(x, ROUTES[f"route_{stop}_{kind}"])


@pytest.mark.parametrize("stop", ["olivine_01", "olivine_02", "carbonate_01", "carbonate_02"])
def test_balanced_matches_handoff_pareto(client, stop):
    rs = client.post("/routes", json={"from": {"waypoint_id": "habitat_01"}, "to": {"waypoint_id": stop},
                                      "round_trip": True, "dwell_min": 30}).json()["routes"]
    bal = [r for r in rs if r["label"] == "balanced"]
    assert len(bal) == 1
    same(bal[0], ROUTES[f"route_{stop}_pareto"])


@pytest.mark.parametrize("stop", STOPS)
def test_via_shelter_matches_handoff(client, stop):
    x = client.post("/api/routes/via-shelter", json={"to": {"waypoint_id": stop}}).json()["routes"][0]
    same(x, ROUTES[f"route_{stop}_via_shelter"])


def test_all_28_saved_routes_are_checked():
    checked = {f"route_{s}_{k}" for s in STOPS for k in ("fastest", "easiest", "via_shelter")}
    checked |= {f"route_{s}_pareto" for s in ["olivine_01", "olivine_02", "carbonate_01", "carbonate_02"]}
    checked |= {"route_budget_1h", "route_budget_1_5h", "route_budget_2h", "route_budget_3h", "route_budget_4h",
                "route_tour_all_stops"}
    assert checked == set(ROUTES) and len(ROUTES) == 28


def test_engine_is_the_single_source():
    from routing.export_handoff import Exporter
    from api.main import engine
    assert isinstance(engine().X, Exporter) and engine().X.dose_rate is not None


def test_pareto_endpoint(client):
    j = client.post("/api/routes/pareto", json={"to": {"waypoint_id": "carbonate_01"}}).json()
    rs = j["routes"]
    assert 1 <= len(rs) <= 5 and j["oxygen_verified"] is False
    assert [r["time_min"] for r in rs] == sorted(r["time_min"] for r in rs)
    assert all("warnings" in r for r in rs)


@pytest.mark.parametrize("budget_h,rid", [(1, "route_budget_1h"), (1.5, "route_budget_1_5h"), (2, "route_budget_2h"),
                                          (3, "route_budget_3h"), (4, "route_budget_4h"), (6, "route_tour_all_stops")])
def test_time_budget_tour_matches_handoff(client, budget_h, rid):
    j = client.post("/api/routes/time-budget", json={"time_budget_min": budget_h * 60}).json()
    same(j["best_tour"], ROUTES[rid])
    assert all(r["total_time_min"] <= budget_h * 60 for r in j["single_stop"])


@pytest.mark.parametrize("sid", list(EMERG))
def test_emergency_matches_handoff(client, sid):
    s = EMERG[sid]
    j = client.post("/api/emergency/reachable", json={"position": {"waypoint_id": s["start_waypoint_id"]},
                                                      "suit_supply_left_h": s["suit_supply_left_h"]}).json()
    assert j["oxygen_verified"] is False
    for k in ("start", "suit_supply_left_h", "reserve_fraction", "usable_h", "route_choice", "destinations"):
        assert j[k] == s[k], k


def test_mineral_target(client):
    rs = client.post("/api/routes/mineral-target", json={"mineral": "clay"}).json()["routes"]
    assert {r["destination_waypoint_id"] for r in rs} == {"clay_01", "clay_02"}


def test_position_forms_agree(client):
    w = {x["id"]: x for x in client.get("/api/scientific-destinations").json()["waypoints"]}["carbonate_01"]
    a = client.post("/api/routes/easiest", json={"to": {"east_m": w["east_m"], "north_m": w["north_m"]}}).json()
    b = client.post("/api/routes/easiest", json={"to": {"lat": w["lat"], "lon": w["lon"]}}).json()
    for x in (a, b):
        assert x["routes"][0]["destination_waypoint_id"] is None  # a coordinate, not a waypoint
        same(x["routes"][0], ROUTES["route_carbonate_01_easiest"], skip=("destination_waypoint_id",))


def test_mandatory_3_outside_grid_is_422(client):
    r = client.post("/api/routes/easiest", json={"to": {"east_m": 5000, "north_m": 0}})
    assert r.status_code == 422 and r.json()["error"] == "outside_grid"
    r = client.get("/api/terrain/point", params={"lat": 0, "lon": 0})
    assert r.status_code == 422


def test_unknown_waypoint_is_404(client):
    r = client.post("/api/routes/fastest", json={"to": {"waypoint_id": "nope"}})
    assert r.status_code == 404 and set(r.json()) == {"error", "detail"}


def test_bad_body_is_422(client):
    r = client.post("/api/emergency/reachable", json={"position": {"waypoint_id": "clay_01"}})
    assert r.status_code == 422 and set(r.json()) == {"error", "detail"}


def test_terrain_point_and_layers(client):
    p = client.get("/api/terrain/point", params={"east_m": 0, "north_m": 0}).json()
    assert p["walkable"] is True and p["line_of_sight_to_habitat"] is True and p["east_m"] == 0.0
    L = client.get("/api/terrain/layers").json()
    f = L["layers"][0]["file"]
    assert f.startswith("http") and f.endswith(".png")
    assert client.get("/static/map_layers/slope.png").status_code == 200


def test_cors_base44(client):
    r = client.options("/api/routes/easiest", headers={"Origin": "https://jolly-mars-path-pilot.base44.app",
                                                       "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") == "https://jolly-mars-path-pilot.base44.app"
