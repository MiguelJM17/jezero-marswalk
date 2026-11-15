# Jezero Marswalk routing API: finished build (Ronald)

Nov 14, 2026 · Euler's Disappointments

**Status:** built and tested locally. **Not deployed yet.** There is no public URL until someone with access to the Google Cloud project runs the deploy commands in the deployment section.

This is a FastAPI service that wraps Miguel's **current** routing engine (`routing/`, unchanged), the same code that produced `outputs/`. It answers with the same JSON objects as the **30-route** handoff. The endpoints follow `API_CONTRACT.md` v1, which uses the paths the Base44 app already calls.

**One source for every number.** Metrics, terrain slope, radiation, segments with the nearest safe place, geometry and point objects all come from `routing.export_handoff.Exporter`. `api/engine.py` sets up `Exporter` exactly like `export_handoff.main()`. It does not compute any field itself. It only reads positions, returns errors and runs the engine for any start or destination.

## Why this is a new `api/main.py`

An earlier adapter was not available when this was built, so `api/main.py` was written directly from `API_CONTRACT.md`.

- If Valeria's package turns up, the team can choose either version.
- Both versions wrap the same engine.
- This version is checked against the **30-route** handoff. Valeria's was checked against the older 17-route one.

## Test results

**56 tests pass.** That is the 16 engine tests in `tests/test_planner.py` plus 38 API tests in `tests/test_api.py`. They were run on Python 3.13 and on Python 3.10 with the same packages as the Dockerfile.

The API tests compare the live answers with the saved files, field by field. That includes the geometry, the lon/lat lists, the segments, the warnings and the radiation estimate.

| Saved file in `outputs/` | Live call | Result |
|---|---|---|
| 6 `fastest` + 6 `easiest` routes | `POST /api/routes/fastest`, `/easiest` | identical |
| 4 `pareto` routes ("balanced") | `POST /routes` (weights 1, 0.5, 0, as in the export) | identical |
| `route_budget_1h` … `route_budget_4h` (5 routes) and `route_tour_all_stops` | `POST /api/routes/time-budget` → `best_tour` | identical |
| 4 emergency scenarios (olivine_02 and carbonate_02, 1 h and 2 h) | `POST /api/emergency/reachable` | identical |
| 6 `via_shelter` routes | `POST /api/routes/via-shelter` (extra endpoint, not in the contract) | identical |
| `carbonate_01` given as east/north and as lat/lon | `POST /api/routes/easiest` | identical route |

That covers **all 30 saved routes**. A test (`test_all_28_saved_routes_are_checked` (now set-based)) fails if a saved route is ever left without a live comparison.

**Regenerating the handoff with the new engine (Miguel's step 4).** I ran `routing.export_handoff` with the current engine:
- It gives 30 routes, 4 emergency scenarios, 13 waypoints and 16 mineral patches.
- It takes about 20 s.
- `routes.json`, `emergency.json`, `waypoints.json`, `conditions.json`, `mission_config.json`, `layers_manifest.json`, `route_model.json` and `rover_positions.json` come out **byte for byte identical** to `outputs/`.
- The map PNGs have identical pixels. Only the PNG compression bytes differ.

Two inputs are not in `data/`, so I had to supply them:
- **RAD:** the Curiosity CDF files are not in `data/rad`, and CDAWeb cannot be reached from my environment. For the comparison I passed the saved RAD summary from `conditions.json` (`tools/export_with_saved_rad.py`, run from this folder). Without it, the export still runs, but routes, emergencies and shelters have no radiation fields.
- **MEDA:** `data/meda_pressure_summary.json` is the `per_sol` list copied from `conditions.json`.

One harmless difference remains, in `minerals.json`: `clay_patch_13` and `clay_patch_14` have the same area (1304 m²), and their order flips. `np.argsort` does not guarantee the order of ties. Using `np.argsort(-sizes, kind="stable")` would fix it.

**The three mandatory checks from the contract:**

1. `POST /api/routes/easiest` with `{"to": {"waypoint_id": "carbonate_01"}}` gives:
   - 1162.7 m
   - 29.3 min
   - effort 0.77
   - max_slope_deg 27.1
   - max_terrain_slope_deg 33.9

   This matches `route_carbonate_01_easiest` ✔
2. `POST /api/emergency/reachable` from olivine_02 with 1 h left matches `emergency_olivine_02_1h` in every destination and every field ✔
3. A point outside the grid returns **422** with `{"error": "outside_grid", ...}` ✔

**Performance, measured on my machine:**

| Measure | Value |
|---|---|
| Startup | about 10 s (terrain, graph, sky view, line of sight and safe-place times load once) |
| Single route | about 0.3 s |
| `time-budget` (7 Dijkstra runs plus an exhaustive tour search) | about 3 s |
| Memory | about 470 MB (RSS), so 1 GiB on Cloud Run leaves room |

## Run it locally

```bash
pip install -r requirements.txt -r api/requirements-api.txt
python -m pytest -q                    # 56 passed
uvicorn api.main:app --port 8080
```

Then open:
- `http://localhost:8080/api/health`
- `http://localhost:8080/docs`

The same `openapi.json` is in this folder, generated from the app. the Base44 chat asked for it.

## Endpoints

Every position in a request can be given in any of these three forms:
- `{"waypoint_id": "carbonate_01"}`
- `{"east_m": 120, "north_m": -340}` (ground metres from the habitat)
- `{"lat": 18.4537, "lon": 77.4061}`

If `from` is left out, the start is the habitat.

Every route and emergency answer has `"oxygen_verified": false`, and every route has `warnings`. Each route also has `start` and `end` points with east/north, lat/lon and elevation.

`api/examples/` holds a full real request and response for every endpoint. They are generated by the API itself, not written by hand.

| Method and path | Request body or query | Response |
|---|---|---|
| `GET /api/health` | none | `{"ok": true, "grid": "grid5m_jezero_crop", "habitat": {"lat": 18.452739, "lon": 77.405768}}` |
| `POST /api/routes/fastest` | `{"from"?, "to", "round_trip": true, "dwell_min": 30}` | `{"routes": [route], "oxygen_verified": false}`. The one route minimizes time. |
| `POST /api/routes/easiest` | same | One route that minimizes effort (`label` "preferred (least effort)"). |
| `POST /api/routes/pareto` | same | 1–5 non-dominated routes (weights 1, 0.75, 0.5, 0.25, 0), ordered by time. `type` is `fastest`, `easiest`, `pareto`, or `fastest_and_easiest` when one path is both. |
| `POST /api/routes/via-shelter` (extra) | `{"from"?, "to", "dwell_min": 30}` | One round trip that passes by the best terrain shelter, chosen the same way as `export_handoff`, with `via_waypoint_id`, `extra_time_vs_easiest_min` and `extra_effort_vs_easiest`. |
| `POST /api/routes/mineral-target` | `{"mineral": "carbonate \| olivine \| clay", "from"?, "dwell_min"}` | The pareto round trips to every stop whose `mineral_group` matches. |
| `POST /api/routes/time-budget` | `{"time_budget_min": 120, "from"?, "dwell_min": 30, "multi_stop": true}` | `{"single_stop": [...], "best_tour": route \| null, "oxygen_verified": false}`. See the note below the table. |
| `POST /api/emergency/reachable` | `{"position", "suit_supply_left_h": 2.0, "reserve_fraction": 0.25}` | The same shape as one scenario in `emergency.json`. Destinations are the habitat, the 6 terrain shelters and the nearest point with line of sight to the habitat antenna, ordered by `relative_effort`. |
| `GET /api/scientific-destinations` | none | `waypoints.json` (habitat, 6 stops with photos and pressure, 6 shelters) plus `minerals.json` under `mineral_patches`. |
| `GET /api/terrain/layers` | none | `layers_manifest.json`, with each `file` as an absolute URL `https://<server>/static/map_layers/<id>.png`. |
| `GET /api/terrain/point` | `?east_m=&north_m=` or `?lat=&lon=` | `east_m`, `north_m`, `lat`, `lon`, `elevation_m`, `slope_deg`, `roughness_deg`, `thermal_inertia`, `mineral` {class, name, group, confidence}, `walkable`, `sky_blocked_pct`, `line_of_sight_to_habitat` |

**`time-budget`:**
- `single_stop` lists the least-effort round trip to each stop whose `total_time_min` fits the budget, ordered by total time.
- `best_tour` is `Planner.best_tour`: the most stops within the budget, then the least effort. It includes `stop_order` and `time_budget_h`.

**Extra paths for Valeria's and Miguel's step-2 test:**
- `GET /health`
- `POST /routes`, which returns fastest, balanced and easiest exactly like `routes.json`

**Errors** always look like `{"error": "<code>", "detail": "<text>"}`:

| Status | Codes |
|---|---|
| 404 | `unknown_waypoint` |
| 422 | `outside_grid`, `not_walkable` (the detail says which of the engine's 3 block codes applies), `no_route`, `same_point`, `unknown_mineral`, `invalid_position`, `invalid_request` |
| 500 | `internal_error` |

The API never answers with an estimate in place of a failed calculation.

### Example: mandatory check 1

```bash
curl -X POST http://localhost:8080/api/routes/easiest -H "Content-Type: application/json" \
  -d '{"to":{"waypoint_id":"carbonate_01"}}'
```

The response is shortened here. The full one is in `api/examples/routes_easiest.json`.

```json
{"routes": [{"id": "route_carbonate_01_easiest", "type": "easiest", "label": "preferred (least effort)",
  "start_waypoint_id": "habitat_01", "destination_waypoint_id": "carbonate_01", "round_trip": true,
  "distance_m": 1162.7, "time_min": 29.3, "relative_effort": 0.77, "max_slope_deg": 27.1,
  "max_terrain_slope_deg": 33.9, "m_steeper_than_20deg": 122.2, "m_terrain_steeper_than_20deg": 115.3,
  "m_walking_grade_steeper_than_20deg": 88.7, "radiation_dose_estimate_uGy": 2.34,
  "science_time_min": 30.0, "total_time_min": 59.3, "feasible_recommended_6h": true, "feasible_max_8h": true,
  "warnings": ["122 m on ground or grade steeper than 20 deg (NASA Artemis suit reference); steepest ground 34 deg, steepest walking grade 27 deg"],
  "geometry": {"type": "LineString", "frame": "local ENU from habitat", "coordinates": [[0.0, 0.0], [0.0, 5.0], "..."]},
  "segments": ["..."]}],
 "oxygen_verified": false}
```

### Example: emergency

```bash
curl -X POST http://localhost:8080/api/emergency/reachable -H "Content-Type: application/json" \
  -d '{"position":{"waypoint_id":"olivine_02"},"suit_supply_left_h":1,"reserve_fraction":0.25}'
```

Response, shortened (the full one is in `api/examples/emergency_reachable.json`):
- `usable_h` is 0.75.
- The closest destination is `comms_nearest_los` at 175.3 m, effort 0.067.
- Next are `shelter_04` (0.189) and `habitat_01` (0.229).
- The last three (`shelter_06`, `shelter_03`, `shelter_01`) have `feasible_under_model: false`.

## Deploy to Google Cloud Run

Run this from Cloud Shell, inside this folder. It needs access to project `project-480d8e7f-79f8-45b3-951` with these roles:
- Cloud Run Admin
- Cloud Build Editor
- Artifact Registry Administrator
- Service Account User

Before you start, confirm with Valeria or the project admin that the hackathon credits cover Cloud Run, Cloud Build and Artifact Registry. Billing being enabled does not mean the cost is covered.

**One command does the deploy and checks it** (`tools/deploy_cloud_run.sh`):

```bash
REGION=us-east1 bash tools/deploy_cloud_run.sh                 # private service
REGION=us-east1 PUBLIC=yes bash tools/deploy_cloud_run.sh      # public: only if policy allows and the team agrees
```

What the script does:
1. Sets the project.
2. Enables Cloud Run, Cloud Build and Artifact Registry.
3. Deploys with 1 GiB, 1 CPU, min 0 / max 3 instances and `CORS_ORIGINS`.
4. Runs `tools/check_live_api.py` against the new URL. That check makes 44 tests: health, the 3 mandatory checks, all saved routes, the 4 emergency scenarios, `openapi.json`, the layer PNGs and CORS for each app origin. It stops with an error if any of them fails.

**Notes:**
- Use the region the project allows. `us-east1` is only an example.
- A **private** service is checked with your identity token, but Base44 cannot call a private URL from the browser. For the app, the service has to be public, or Base44 needs an authenticated bridge.

The same check works on its own, against any running copy:

```bash
python3 tools/check_live_api.py https://<URL>                                   # public
python3 tools/check_live_api.py https://<URL> --token "$(gcloud auth print-identity-token)"   # private
python3 tools/check_live_api.py http://localhost:8080                           # local (44 passed here)
```

**Add the marseva.us origins once the domain works.** It is harmless to add them earlier.

```bash
gcloud run services update jezero-marswalk-api --region <REGION> \
  --update-env-vars "^@^CORS_ORIGINS=https://jolly-mars-path-pilot.base44.app,https://marseva.us,https://www.marseva.us"
```

`^@^` tells gcloud that the separator is `@`, so the commas stay inside the value.

**Optional: `api.marseva.us`.** Cloud Run domain mappings are a **Preview** feature, and they work only in these regions:
- asia-east1, asia-northeast1, asia-southeast1
- europe-north1, europe-west1, europe-west4
- us-central1, us-east1, us-east4, us-west1

Before mapping, the Google account that deploys has to verify ownership of `marseva.us` in Search Console. That is a TXT record in Porkbun.

```bash
gcloud domains verify marseva.us                   # opens Search Console; add the TXT record it gives in Porkbun
gcloud beta run domain-mappings create --service jezero-marswalk-api --domain api.marseva.us --region <REGION>
gcloud beta run domain-mappings describe --domain api.marseva.us --region <REGION>   # the DNS record to add in Porkbun
```

The `*.run.app` URL works right away. For the demo, give the app that URL; the custom domain is only cosmetic.

**About the deployment settings:**
- The `Dockerfile` uses `python:3.10-slim` with the pinned packages from `requirements.txt` and `api/requirements-api.txt`. I tested it with Python 3.10 and the same pins.
- I could not build the Docker image here because there is no Docker daemon.
- CORS allows `https://marseva.us`, `https://www.marseva.us` and the app build origin by default. Other origins go in `CORS_ORIGINS`, as shown above.
- The first request after the service has been idle takes about 10 s, because min instances is 0. For the live demo, open `/api/health` a minute before.
- Never put Google credentials or ADC files in the team chat or in Base44.

## Connect it to Base44 (Ronald)

1. In the app, open **Settings → Mars Routing API URL**, paste the URL and save.
2. Open **Science & Data → Integration test**. It checks four things:
   1. the API responds;
   2. the endpoint list from `/openapi.json`;
   3. a real request;
   4. the coordinates fall inside the map.
3. The app should say "Routing API connected" only after a request has worked. If a call fails, the app keeps using the precomputed files and never makes up a result.
4. Attach `openapi.json` in the Base44 chat and paste the prompt in `docs/BASE44_PROMPT.md`.
5. Test Find a Mineral, Plan a Trip and Emergency in the editor. Then click **Publish App** (top right) so the public link uses the API.

## Engine notes for Miguel

1. **The engine is now your current one.** `routing/`, `processing/`, `tests/test_planner.py`, `requirements.txt` and the repo `README.md` are the current engine. The fields previously rebuilt by hand are gone from `api/engine.py`; it calls `Exporter` instead.
2. **Blocked cells.** `blocked_mask` now has 3 codes. Inside the API grid none of them applies: all 320,131 cells are walkable. The grid's west edge is at 77.381°E, east of 77.35°E, and no cell there has thermal inertia below 100. If a request lands on a blocked cell, the 422 says which code applies.
3. **Warning text.** The warning sentence is written inline in `export_handoff.main()`, so the API keeps a copy of the same format string (`Engine.warnings`). The tests compare it with every saved route. If you move it into a function, the API can call it.
4. **Grid size.** The grid is the same window as the export: farthest stop + 800 m, about ±1,373 m. That is what makes the routes come out identical. A point outside it returns 422.
5. **Terrain point minerals.** `/api/terrain/point` uses the engine's `GROUPS` (1 olivine, 2 carbonate, 3/9/10 clay), so classes such as 4 "Olivine + Smectite" get `group: null`.
6. **Your step-4 command.** The default grid folder is `data/processed/grid5m`, which is what `processing/build_grid.py` writes; set `MARSWALK_GRID` if yours is elsewhere. It also needs `curated/rover_waypoints_minerals.csv` for `rover_positions.json`. I added that file.
7. **Stable order for mineral patches.** See the `minerals.json` note in the test results section above.

## Use of AI tools

This API was written with the help of an AI assistant: **Claude (Anthropic)**, used through claude.ai.
- **Ronald** directed the work, made the decisions and ran the checks.
- **Claude** wrote most of the code in `api/`, `tests/test_api.py` and `tools/`, and the first drafts of this README.
- The routing engine (`routing/`) is the team's own code (Miguel). The API calls it and does not change it.

**How the results were checked:**
- The 49 automated tests compare every live answer with the saved, engine-generated files, field by field.
- `tools/check_live_api.py` repeats those comparisons against the deployed service.

Valeria's separate adapter was built with Codex assistance, as stated in her README.

## What to say in the presentation

- **If it is deployed and connected:** "The routing API is live on Google Cloud Run and the app calls it."
- **If not:** "The routing API is built and tested locally (56 tests pass); cloud deployment is next."
