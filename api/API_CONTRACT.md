# API contract: Marswalk routing (API ⇄ app)

v1 · Nov 14, 2026 · Miguel

The **endpoint names are the ones the Base44 app already uses** (app page `/data` → External API). The **response formats are the ones in `base44_handoff/`**. If Valeria builds exactly this, the app only needs the base URL in its Settings.

## General rules
- Base URL: `https://<server>/` (set in the app's Settings). Everything is JSON, UTF-8.
- CORS: allow `https://jolly-mars-path-pilot.base44.app`.
- Coordinates: `east_m` / `north_m` from the habitat (habitat_01 = 0,0), the same frame as `base44_handoff`. Every point also returns `lat`, `lon` and `elevation_m`.
- A **position** in a request can be any one of:
  - `{"waypoint_id": "carbonate_01"}`
  - `{"east_m": 120, "north_m": -340}`
  - `{"lat": 18.4537, "lon": 77.4061}`
- Numbers are never rounded or invented: they come from `routing/` with `config.py`. If something cannot be computed, return an error, never an estimate.
- Always include: `"oxygen_verified": false` in routes and emergency results, and `warnings` on every route.
- Errors: `{"error": "<code>", "detail": "<text>"}`, using:
  - **404** for an unknown `waypoint_id`;
  - **422** for a point outside the grid or a point that can't be walked;
  - **500** for anything else.

  the Base44 app never replaces a failed call with invented results.

## Route object (the same as each element of `routes.json` → `routes`)
```json
{
  "id": "route_carbonate_01_easiest",
  "type": "fastest | easiest | fastest_and_easiest | pareto | multi_stop",
  "label": "preferred (least effort)",
  "start_waypoint_id": "habitat_01",
  "destination_waypoint_id": "carbonate_01",
  "round_trip": true,
  "geometry": {"type": "LineString", "frame": "local ENU from habitat", "coordinates": [[east_m, north_m], ...]},
  "lonlat": [[lon, lat], ...],
  "distance_m": 1162.7, "time_min": 29.3, "relative_effort": 0.77,
  "max_slope_deg": 27.1, "max_terrain_slope_deg": 33.9,
  "m_walking_grade_steeper_than_20deg": 88.7, "m_terrain_steeper_than_20deg": 115.3, "m_steeper_than_20deg": 122.2,
  "climb_m": 0, "descent_m": 0,
  "science_time_min": 30, "total_time_min": 59.3,
  "feasible_recommended_6h": true, "feasible_max_8h": true,
  "warnings": ["..."],
  "segments": [{"start": [e, n], "end": [e, n], "distance_m": 0, "time_min": 0, "relative_effort": 0,
                "max_slope_deg": 0, "max_terrain_slope_deg": 0, "elevation_change_m": 0}]
}
```
Units: `relative_effort` is in **hours of suit supply at 1200 BTU/h** (model, not verified). Field definitions: `routes.json` → `field_definitions`.

## Endpoints

### POST /api/routes/fastest · /api/routes/easiest · /api/routes/pareto
Request:
```json
{"from": <position>, "to": <position>, "round_trip": true, "dwell_min": 30}
```
Defaults: `from` = habitat, `round_trip` = true, `dwell_min` = 30.

Response: `{"routes": [<route>], "oxygen_verified": false}`
- `fastest`: one route, the one that minimizes time.
- `easiest`: one route, the one that minimizes effort.
- `pareto`: the non-dominated routes (between 1 and 5), ordered by time, with `type` and `label` filled in.

### POST /api/routes/mineral-target
Request: `{"mineral": "carbonate | olivine | clay", "from": <position>, "dwell_min": 30}`

Response: `{"routes": [<route>...], "oxygen_verified": false}`. These are the pareto routes, round trip, to every science stop of that mineral (`waypoints.json`, `mineral_group`).

### POST /api/routes/time-budget
Request: `{"time_budget_min": 120, "from": <position>, "dwell_min": 30, "multi_stop": true}`

Response:
```json
{"single_stop": [<route>...], "best_tour": <route type multi_stop> | null, "oxygen_verified": false}
```
- `single_stop`: round-trip routes to each stop whose `total_time_min` ≤ budget, ordered by time.
- `best_tour`: visits the most stops within the budget, then the least effort (the same as `Planner.best_tour`).

### POST /api/emergency/reachable
Request: `{"position": <position>, "suit_supply_left_h": 2.0, "reserve_fraction": 0.25}`

Response: the same as one scenario in `emergency.json`:
```json
{"start": {...}, "suit_supply_left_h": 2.0, "reserve_fraction": 0.25, "usable_h": 1.5,
 "route_choice": "least effort", "oxygen_verified": false,
 "destinations": [{"destination_id": "habitat_01", "kind": "base | candidate_shelter | communication_point",
                   "reachable": true, "feasible_under_model": true, "distance_m": 0, "time_min": 0,
                   "relative_effort": 0, "max_slope_deg": 0, "max_terrain_slope_deg": 0,
                   "geometry": {...}}]}
```
Destinations are ordered by `relative_effort`. The communication point is the walkable cell nearest to the start that has line of sight to the habitat antenna.

### GET /api/scientific-destinations
Response: the content of `waypoints.json` (habitat, 6 stops with `photos` and `pressure_pa`, refuges) plus `minerals.json` under `"mineral_patches"`.

### GET /api/terrain/layers
Response: `layers_manifest.json`, with each layer's `file` as an absolute URL (for example `https://<server>/static/map_layers/slope.png`). The PNGs are served as static files.

### GET /api/terrain/point?east_m=..&north_m=..   (or ?lat=..&lon=..)
Response:
```json
{"east_m": 0, "north_m": 0, "lat": 0, "lon": 0, "elevation_m": 0, "slope_deg": 0, "roughness_deg": 0,
 "thermal_inertia": 0, "mineral": {"class": 0, "group": "carbonate | olivine | clay | null", "confidence": "high | medium | none"},
 "walkable": true, "sky_blocked_pct": 0, "line_of_sight_to_habitat": true}
```

### GET /api/health (extra, for the app's "Test" button)
`{"ok": true, "grid": "grid5m_jezero_crop", "habitat": {"lat": 18.452739, "lon": 77.405768}}`

## Mandatory checks before saying it's ready
1. `POST /api/routes/easiest` with `{"to": {"waypoint_id": "carbonate_01"}}` must give the same numbers as `route_carbonate_01_easiest` in `routes.json`: 1162.7 m, 29.3 min, effort 0.77, max_slope_deg 27.1, max_terrain_slope_deg 33.9.
2. `POST /api/emergency/reachable` with `{"position": {"waypoint_id": "olivine_02"}, "suit_supply_left_h": 1}` must give the same as `emergency_olivine_02_1h`.
3. A point outside the grid returns a 422, not a route.

## Performance
- Load `Area` and `Planner` once at startup, for an area of about ±1.4 km around the habitat. Each route takes about 0.3–0.4 s; the emergency query is one Dijkstra.
- Memory: about 300 MB.
- Free deployment: Hugging Face Spaces (Docker) or Cloud Run if billing is available.
