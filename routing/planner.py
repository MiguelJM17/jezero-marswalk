"""Route engine: terrain graph, routes, alternatives, multi-stop plans, emergency.

Graph
-----
Each walkable cell is a vertex joined to its 8 neighbours. The graph is directed
because going up costs more than going down. Every edge carries:
  time_s     walking time (Tobler speed model, rescaled to the Apollo flat speed)
  effort     metabolic energy in "oxygen-hours": hours of suit supply at the
             reference rate (1200 BTU/h). effort = time_h * Pandolf rate relative to flat
  dist_m     ground distance
Edges that touch a blocked cell do not exist (no elevation, thermal inertia < 100,
west DTM artefact zone; see terrain.blocked_mask). Steep grade is NOT a block: it
costs more time and effort and is reported as a warning above MAX_SLOPE_DEG.

Shortest paths use Dijkstra (scipy.sparse.csgraph), which returns the exact optimum;
A* returns the same paths and only differs in speed.
"""
import itertools
import math

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from . import config as C
from .terrain import Area, blocked_mask, terrain_factor, warning_flags

NEIGH = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
TAN_MAX = math.tan(math.radians(C.MAX_SLOPE_DEG))


def tobler_kmh(s):
    flat = C.TOBLER_A * math.exp(-C.TOBLER_B * C.TOBLER_C)
    v = C.TOBLER_A * np.exp(-C.TOBLER_B * np.abs(s + C.TOBLER_C))
    return v * (C.FLAT_SPEED_KMH / flat)


FLAT_V_MS = C.FLAT_SPEED_KMH / 3.6


def metabolic_rel(s, v_ms, eta):
    """Pandolf metabolic rate relative to walking on flat, smooth ground at the flat speed.
    Pandolf (no load): M = W * [1.5 + eta * (1.5 V^2 + 0.35 V G)]; body weight W cancels.
    Includes the standing term (1.5 W), so slow walking is not over-penalised.
    Downhill (G < 0) is counted as flat (team decision: never cheaper than flat)."""
    g = np.maximum(100.0 * s, 0.0) if C.DOWNHILL_MIN_REL >= 1.0 else 100.0 * s
    m = C.PANDOLF_STAND_COEF + eta * (C.PANDOLF_SPEED_COEF * v_ms ** 2 + C.PANDOLF_GRADE_COEF * v_ms * g)
    m0 = C.PANDOLF_STAND_COEF + C.PANDOLF_SPEED_COEF * FLAT_V_MS ** 2
    return m / m0


class Planner:
    def __init__(self, area: Area):
        self.a = area
        H, W = area.shape
        self.H, self.W = H, W
        self.block = blocked_mask(area)
        self.eta = terrain_factor(area)
        self.warn = warning_flags(area)
        ok = self.block == 0
        z = area.z
        src, dst, t_, e_ = [], [], [], []
        for di, dj in NEIGH:
            r0, r1 = max(0, -di), H - max(0, di)
            c0, c1 = max(0, -dj), W - max(0, dj)
            u_ok = ok[r0:r1, c0:c1]
            v_ok = ok[r0 + di:r1 + di, c0 + dj:c1 + dj]
            dz = z[r0 + di:r1 + di, c0 + dj:c1 + dj] - z[r0:r1, c0:c1]
            dist = math.hypot(dj * area.dx, di * area.dy)
            s = dz / dist
            m = u_ok & v_ok
            rr, cc = np.nonzero(m)
            rr, cc = rr + r0, cc + c0
            t, eff = self._edge_costs(s[m], dist, self.eta[rr, cc], self.eta[rr + di, cc + dj])
            src.append((rr * W + cc).astype(np.int32))
            dst.append(((rr + di) * W + (cc + dj)).astype(np.int32))
            t_.append(t.astype(np.float32))
            e_.append(eff.astype(np.float32))
            del dz, s, m, rr, cc
        self.src, self.dst = np.concatenate(src), np.concatenate(dst)
        self.t = np.concatenate(t_)
        self.e = np.concatenate(e_)
        del src, dst, t_, e_
        self.n = H * W
        self._G = {}

    @staticmethod
    def _edge_costs(s, dist, eta_u, eta_v):
        """time (s) and effort (oxygen-hours) for steps of grade s and length dist."""
        v_ms = tobler_kmh(s) / 3.6
        t = dist / v_ms
        eff = (t / 3600.0) * metabolic_rel(s, v_ms, 0.5 * (eta_u + eta_v))
        return t, eff

    # ---------------------------------------------------------------- graphs
    def graph(self, w_time):
        """Weighted blend: w_time=1 -> fastest, 0 -> least effort.
        On flat smooth ground 1 h of walking = 1 oxygen-hour, so both are in hours."""
        k = round(w_time, 3)
        if k not in self._G:
            if len(self._G) >= 3:  # keep memory bounded on large grids
                self._G.pop(next(iter(self._G)))
            w = (k * (self.t / np.float32(3600.0)) + (1 - k) * self.e).astype(np.float32)
            self._G[k] = csr_matrix((w, (self.src, self.dst)), shape=(self.n, self.n))
        return self._G[k]

    def idx(self, rc):
        return rc[0] * self.W + rc[1]

    def rc(self, i):
        return divmod(int(i), self.W)

    def walkable(self, rc):
        r, c = rc
        return 0 <= r < self.H and 0 <= c < self.W and self.block[r, c] == 0

    # ---------------------------------------------------------------- paths
    def tree(self, start_rc, w_time, reverse=False):
        G = self.graph(w_time)
        if reverse:
            G = G.T.tocsr()
        dist, pred = dijkstra(G, indices=self.idx(start_rc), return_predecessors=True)
        return dist, pred

    @staticmethod
    def _walk(pred, target):
        path = [target]
        while pred[path[-1]] >= 0:
            path.append(pred[path[-1]])
        return path[::-1]

    def path(self, a_rc, b_rc, w_time):
        dist, pred = self.tree(a_rc, w_time)
        ib = self.idx(b_rc)
        if not np.isfinite(dist[ib]):
            return None
        return self._walk(pred, ib)

    def stats(self, nodes):
        """Recompute segment statistics along a path with the same cost model."""
        rc = np.array([divmod(int(i), self.W) for i in nodes])
        if len(rc) < 2:
            return {"distance_m": 0.0, "time_h": 0.0, "effort_o2_h": 0.0, "max_grade_deg": 0.0,
                    "climb_m": 0.0, "descent_m": 0.0, "m_above_slope_limit": 0.0, "m_soft_soil_warning": 0.0,
                    "mean_roughness_deg": 0.0, "mean_thermal_inertia": 0.0}
        d_rc = np.diff(rc, axis=0)
        dist = np.hypot(d_rc[:, 1] * self.a.dx, d_rc[:, 0] * self.a.dy)
        z = self.a.z[rc[:, 0], rc[:, 1]]
        dz = np.diff(z)
        s = dz / dist
        eta = self.eta[rc[:, 0], rc[:, 1]]
        t, eff = self._edge_costs(s, dist, eta[:-1], eta[1:])
        return {
            "distance_m": float(dist.sum()),
            "time_h": float(t.sum() / 3600.0),
            "effort_o2_h": float(eff.sum()),
            "max_grade_deg": float(np.degrees(np.arctan(np.abs(s).max()))),
            "length_over_reference_slope_m": float(dist[np.abs(s) > TAN_MAX].sum()),
            "climb_m": float(dz[dz > 0].sum()),
            "descent_m": float(-dz[dz < 0].sum()),
            "m_above_slope_limit": float(dist[(np.abs(s) > TAN_MAX) |
                                              (self.warn[rc[1:, 0], rc[1:, 1]] & 1).astype(bool)].sum()),
            "m_soft_soil_warning": float(dist[(self.warn[rc[1:, 0], rc[1:, 1]] & 2).astype(bool)].sum()),
            "mean_roughness_deg": float(np.nanmean(self.a.rough[rc[:, 0], rc[:, 1]])),
            "mean_thermal_inertia": float(np.mean(self.a.ti[rc[:, 0], rc[:, 1]])),
        }

    def polyline(self, nodes, base_rc):
        out = []
        for i in nodes:
            r, c = self.rc(i)
            lon, lat = self.a.rc_to_lonlat(r, c)
            e, n = self.a.enu(r, c, *base_rc)
            out.append([round(lon, 6), round(lat, 6), round(e, 1), round(n, 1), round(float(self.a.z[r, c]), 1)])
        return out

    # ---------------------------------------------------------------- alternatives
    def alternatives(self, a_rc, b_rc, weights=(1.0, 0.75, 0.5, 0.25, 0.0)):
        """Fastest, easiest and the non-dominated routes in between (Pareto front)."""
        found = []
        for w in weights:
            p = self.path(a_rc, b_rc, w)
            if p is None:
                return []
            st = self.stats(p)
            if any(p == f["nodes"] for f in found):
                continue
            found.append({"w_time": w, "nodes": p, **st})
        nd = [f for f in found if not any(
            (g["time_h"] <= f["time_h"] and g["effort_o2_h"] <= f["effort_o2_h"]) and
            (g["time_h"] < f["time_h"] or g["effort_o2_h"] < f["effort_o2_h"]) for g in found)]
        nd.sort(key=lambda f: f["time_h"])
        if nd:
            nd[0]["label"] = "fastest"
            easiest = min(nd, key=lambda f: f["effort_o2_h"])
            easiest["label"] = "preferred (least effort)" if easiest is not nd[0] else "preferred (fastest & least effort)"
            easiest["preferred"] = True
            for f in nd:
                f.setdefault("label", "balanced")
                f.setdefault("preferred", False)
            nd.sort(key=lambda f: (not f["preferred"], f["time_h"]))
        return nd

    # ---------------------------------------------------------------- multi-stop
    def matrix(self, points, w_time):
        """Pairwise cost/time/effort/paths between points (list of rc)."""
        n = len(points)
        paths = {}
        for i, p in enumerate(points):
            dist, pred = self.tree(p, w_time)
            for j, q in enumerate(points):
                if i != j:
                    iq = self.idx(q)
                    paths[(i, j)] = self._walk(pred, iq) if np.isfinite(dist[iq]) else None
        return paths

    def best_tour(self, base_rc, stops, w_time, dwell_h, budget_h):
        """Visit the largest subset of stops (then lowest effort) and return to base
        within budget_h. Exhaustive search; fine for up to ~7 stops."""
        pts = [base_rc] + list(stops)
        paths = self.matrix(pts, w_time)
        leg = {k: (self.stats(v) if v else None) for k, v in paths.items()}
        best = None
        idxs = list(range(1, len(pts)))
        for k in range(len(idxs), 0, -1):
            for subset in itertools.combinations(idxs, k):
                for order in itertools.permutations(subset):
                    seq = (0,) + order + (0,)
                    legs = [leg[(seq[i], seq[i + 1])] for i in range(len(seq) - 1)]
                    if any(l is None for l in legs):
                        continue
                    t = sum(l["time_h"] for l in legs) + dwell_h * k
                    e = sum(l["effort_o2_h"] for l in legs)
                    if t <= budget_h and (best is None or e < best["effort_o2_h"]):
                        best = {"order": seq, "time_h": t, "effort_o2_h": e, "legs": legs,
                                "paths": [paths[(seq[i], seq[i + 1])] for i in range(len(seq) - 1)]}
            if best:
                return best
        return None

    # ---------------------------------------------------------------- emergency
    def emergency(self, here_rc, o2_h_left, targets, margin=C.EMERGENCY_MARGIN):
        """targets: list of (name, kind, rc). Returns them ranked by oxygen needed,
        using the least-effort route from the current position."""
        usable = o2_h_left * (1.0 - margin)
        dist, pred = self.tree(here_rc, 0.0)  # least oxygen
        out = []
        for name, kind, rc in targets:
            i = self.idx(rc)
            if not np.isfinite(dist[i]):
                out.append({"name": name, "kind": kind, "reachable": False})
                continue
            nodes = self._walk(pred, i)
            st = self.stats(nodes)
            out.append({"name": name, "kind": kind, "reachable": True,
                        "feasible": st["effort_o2_h"] <= usable, "nodes": nodes, **st})
        out.sort(key=lambda d: d.get("effort_o2_h", math.inf))
        return {"o2_h_left": o2_h_left, "margin": margin, "usable_o2_h": usable, "options": out}
