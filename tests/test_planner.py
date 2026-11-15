"""Tests on small hand-made TEST grids (not Mars data)."""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from routing.planner import Planner, tobler_kmh  # noqa: E402
from routing.terrain import Area, line_of_sight, sky_blocked_fraction  # noqa: E402


def make_area(z, ti=400.0, rough=0.0, lat_deg=0.0):
    z = np.asarray(z, float)
    R = 3396190.0
    H, W = z.shape
    cell = 10.0
    y_center = math.radians(lat_deg) * R
    gy, gx = np.gradient(z, cell)
    slope = np.degrees(np.arctan(np.hypot(gx / math.cos(math.radians(lat_deg)), gy)))
    return Area(z=z, slope=slope, rough=np.full_like(z, rough), ti=np.full_like(z, ti),
                mineral=np.zeros(z.shape, np.uint8), mconf=np.zeros(z.shape, np.uint8),
                x0=0.0, y0=y_center + 0.5 * H * cell, cell=cell, R=R, minerals={})


def test_flat_speed_matches_apollo():
    assert abs(float(tobler_kmh(np.array([0.0]))[0]) - 3.6) < 1e-9


def test_flat_straight_line():
    p = Planner(make_area(np.zeros((5, 21))))
    nodes = p.path((2, 0), (2, 20), 1.0)
    st = p.stats(nodes)
    assert abs(st["distance_m"] - 200.0) < 1e-6
    assert abs(st["time_h"] - 0.2 / 3.6) < 1e-6
    assert abs(st["effort_o2_h"] - st["time_h"]) < 1e-9  # flat & smooth: effort == time


def test_wall_is_avoided():
    z = np.zeros((21, 21))
    z[0:18, 10] = 50.0  # steep wall with a gap at the bottom rows
    p = Planner(make_area(z))
    nodes = p.path((2, 2), (2, 18), 1.0)
    cols = {p.rc(i)[1] for i in nodes}
    rows = [p.rc(i)[0] for i in nodes if p.rc(i)[1] == 10]
    assert 10 in cols and min(rows) >= 18  # crossed only through the gap


def test_no_route_through_missing_data():
    z = np.zeros((11, 11))
    z[:, 5] = np.nan  # a strip with no elevation data is the only hard barrier
    p = Planner(make_area(z))
    assert p.path((5, 0), (5, 10), 1.0) is None


def test_steep_crossing_allowed_but_reported():
    z = np.zeros((11, 11))
    z[:, 5] = 6.0  # a steep ridge across the whole map (no way around)
    p = Planner(make_area(z))
    nodes = p.path((5, 0), (5, 10), 0.0)
    assert nodes is not None
    assert p.stats(nodes)["m_above_slope_limit"] > 0


def test_uphill_costs_more_than_downhill():
    z = np.tile(np.arange(21) * 1.0, (3, 1))  # 10% grade rising to the east
    p = Planner(make_area(z))
    up = p.stats(p.path((1, 0), (1, 20), 0.0))
    down = p.stats(p.path((1, 20), (1, 0), 0.0))
    assert up["effort_o2_h"] > down["effort_o2_h"]


def test_alternatives_tradeoff():
    # short route over a hill vs long flat detour
    z = np.zeros((31, 31))
    for r in range(31):
        for c in range(31):
            z[r, c] = max(0.0, 30.0 - 2.5 * math.hypot(r - 15, c - 15))
    p = Planner(make_area(z))
    alts = p.alternatives((15, 0), (15, 30))
    assert alts and alts[0]["preferred"]
    assert alts[0]["effort_o2_h"] == min(a["effort_o2_h"] for a in alts)
    alts = sorted(alts, key=lambda a: a["time_h"])
    assert alts[0]["label"] == "fastest"
    times = [a["time_h"] for a in alts]
    efforts = [a["effort_o2_h"] for a in alts]
    assert times == sorted(times)
    assert efforts == sorted(efforts, reverse=True)


def test_latitude_shrinks_east_west_distance():
    p0 = Planner(make_area(np.zeros((3, 11)), lat_deg=0.0))
    p60 = Planner(make_area(np.zeros((3, 11)), lat_deg=60.0))
    d0 = p0.stats(p0.path((1, 0), (1, 10), 1.0))["distance_m"]
    d60 = p60.stats(p60.path((1, 0), (1, 10), 1.0))["distance_m"]
    assert abs(d60 - d0 * 0.5) < 1.0


def test_emergency_filters_by_oxygen():
    p = Planner(make_area(np.zeros((5, 101))))
    targets = [("near", "shelter", (2, 10)), ("far", "base", (2, 100))]
    # 1 km at 3.6 km/h = 0.2778 h; give 0.2 h usable -> only "near" (100 m) is feasible
    res = p.emergency((2, 0), o2_h_left=0.2 / 0.75, targets=targets, margin=0.25)
    feas = {o["name"]: o["feasible"] for o in res["options"]}
    assert feas == {"near": True, "far": False}


def test_tour_respects_budget():
    p = Planner(make_area(np.zeros((5, 101))))
    stops = [(2, 20), (2, 90)]
    t = p.best_tour((2, 0), stops, 1.0, dwell_h=0.0, budget_h=0.2)  # 400 m round trip fits, 1.8 km not
    assert t is not None and t["order"] == (0, 1, 0)


def test_knight_moves_do_not_fly_over_a_thin_ridge():
    """A knight move spans two cells and is priced from its ends, so it must not exist
    where a one-cell ridge sits between them: crossing would otherwise be free."""
    z = np.zeros((11, 11))
    z[:, 5] = 6.0                      # a one-cell ridge across the whole map
    p = Planner(make_area(z))
    st = p.stats(p.path((5, 0), (5, 10), 0.0))
    assert st["m_above_slope_limit"] > 0       # the ridge is climbed, not skipped
    assert st["climb_m"] >= 6.0 - 1e-9


def test_knight_moves_shorten_a_diagonal_on_open_ground():
    """16 headings beat 8 on a bearing between the axes: the staircase gets shorter."""
    p = Planner(make_area(np.zeros((41, 41))))
    d16 = p.stats(p.path((0, 0), (10, 20), 1.0))["distance_m"]
    straight = math.hypot(20 * p.a.dx, 10 * p.a.dy)
    assert d16 < straight * 1.03               # 8-connected would be about 8% long here


def test_side_slope_splits_the_terrain_slope():
    """tan(terrain)^2 = tan(grade)^2 + tan(side)^2, so a 28 deg walking grade across
    40 deg ground is a 33 deg side slope, and walking straight up it is none."""
    from routing.planner import side_slope_deg  # noqa: E402
    g28 = math.tan(math.radians(28.0))
    g40 = math.tan(math.radians(40.0))
    assert abs(float(side_slope_deg(np.array([40.0]), np.array([g28]))[0]) - 33.0) < 0.1
    assert float(side_slope_deg(np.array([40.0]), np.array([g40]))[0]) < 1e-6
    assert float(side_slope_deg(np.array([0.0]), np.array([0.0]))[0]) == 0.0


def test_standing_costs_half_of_flat_walking():
    """Pandolf with V = 0 leaves only the standing term, so a stop costs half the
    supply rate of walking on flat ground. Derived from the same constants."""
    from routing.planner import standing_rel  # noqa: E402
    assert abs(standing_rel() - 0.5) < 1e-12


def test_flat_route_reports_no_side_slope():
    p = Planner(make_area(np.zeros((5, 21))))
    st = p.stats(p.path((2, 0), (2, 20), 1.0))
    assert st["max_side_slope_deg"] == 0.0 and st["m_side_slope_over_reference"] == 0.0


def test_line_of_sight_and_skyview():
    z = np.zeros((21, 21))
    z[:, 10] = 30.0
    a = make_area(z)
    vis = line_of_sight(a, 10, 2)
    assert vis[10, 5] and not vis[10, 18]
    sky = sky_blocked_fraction(a, radius_m=100.0, n_az=8)
    assert sky[10, 9] > sky[10, 2]


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("ok", k)
