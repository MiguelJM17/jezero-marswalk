# Euler's Disappointments: Marswalk route API (bundle for Valeria)

The goal is an HTTP API that the Base44 app can call to get routes **live** for any point the astronaut chooses, in **exactly the same JSON format** as the precomputed files in `outputs/` (the app imports those). When the API is ready, the app only changes where the data comes from.

## What's in the bundle
| Folder | Contents |
|---|---|
| `routing/` | The engine, already working. `config.py` (all constants, each with its source), `terrain.py` (reads the grid, sky view, line of sight), `planner.py` (graph, Dijkstra, alternatives, tour, emergency), `export_handoff.py` (**builds the JSON objects the app uses: reuse these functions**), `run_plan.py`, `plot_plan.py` |
| `tests/` | 11 tests on synthetic terrain (`python3 -m pytest -q tests`) |
| `data/grid5m_jezero_crop/` | NASA layers on a 5 m grid, ±3 km around the habitat (elevation, slope, roughness, thermal inertia, CRISM minerals) plus `grid.json`. 14 MB. With this crop the routes come out **identical** to the full grid (verified). |
| `outputs/` | The format contract: what the app already has. The API must answer with these same objects and fields. Start with `README_sources.md`. |
| `curated/proposed_stops.csv` | The 6 stops and the habitat (option A) |
| `processing/build_grid.py`, `scripts/download_rad.sh` | How the grid and radiation data were built (reference only; the API doesn't need them) |

## Test that it works (5 minutes)
```bash
pip install -r requirements.txt
python3 -m routing.export_handoff --grid data/grid5m_jezero_crop --stops curated/proposed_stops.csv \
  --option A --base-lat 18.452739 --base-lon 77.405768 --out /tmp/test_handoff
```
It should print `17 routes, 4 emergency scenarios` in about 9 s and use about 300 MB of RAM.

## Proposed endpoints (you decide the final design)
Positions can be sent as `{"waypoint_id": "carbonate_01"}`, `{"lat":..,"lon":..}` or `{"east_m":..,"north_m":..}` (metres from the habitat).

| Method | Path | Request | Response (same format as) |
|---|---|---|---|
| GET | `/health` | | `{"ok": true}` |
| GET | `/mission` | | `mission_config.json` |
| GET | `/waypoints` | | `waypoints.json` |
| GET | `/minerals` | | `minerals.json` |
| GET | `/layers` and `/layers/{id}.png` | | `layers_manifest.json` and the PNGs |
| POST | `/routes` | `{from, to, round_trip: true, dwell_min: 30}` | `{"routes": [...]}` like `routes.json` (fastest / easiest / pareto) |
| POST | `/plan` | `{"mineral": "carbonate"}` or `{"time_budget_min": 120}` | routes to every matching stop, already filtered by `total_time_min` |
| POST | `/tour` | `{stop_ids: [...], budget_h: 6, dwell_min: 30}` | one `multi_stop` route |
| POST | `/emergency` | `{position, suit_supply_left_h: 2, reserve_fraction: 0.25}` | one scenario like those in `emergency.json` |

## Technical notes
- **Load `Area` and `Planner` once at startup**, not on every request: building the graph takes ~0.2 s and caches up to 3 weight graphs. Each route then takes ~0.3–0.4 s.
- Do not change the model or round numbers in the API. If something in the model needs to change, it goes in `config.py`, and the precomputed JSON is regenerated so both stay the same.
- Keep these fields exactly as they are: `oxygen_verified: false`, `warnings`, and the `frame`.
- Slope: there is no 20° mask. It is only a warning (team decision).
- Answer 422 when a point is outside the grid, and 404 for an unknown `waypoint_id`.
- CORS: allow the Base44 app's domain.
- The base and stops are already in `curated/proposed_stops.csv`. The corrected habitat is 18.452739, 77.405768.

## Deployment (Google Cloud Run)
Miguel creates the Google Cloud project and enables Cloud Run and Cloud Build. You write the code and a `Dockerfile`:
- `python:3.10-slim`, `pip install -r requirements.txt fastapi uvicorn`, copy `routing/` and `data/`;
- `CMD uvicorn api.main:app --host 0.0.0.0 --port $PORT`;
- Cloud Run settings: 1 GiB of memory, 1 CPU, min instances 0. Deploy with `gcloud run deploy --source .` from Cloud Shell.

## What we need back
A short README with: the final endpoints and an example request and response for each, the API URL, how to run it locally, and anything in the engine that didn't work or that you would change.
