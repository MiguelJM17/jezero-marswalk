# Routing API

A FastAPI service that wraps the routing engine in `routing/` and answers with the
same JSON objects as the saved files in `outputs/`. It exists so the front end can
ask for a route to **any** point, instead of only the 30 routes computed ahead of
time.

**Status: built and tested locally, not deployed.** 56 tests pass (16 engine, 40
API), on Python 3.13 and on the Dockerfile's 3.10. All 30 saved routes and all 4
emergency scenarios come out identical, field by field, from the live service.

## Run it

```bash
pip install -r requirements.txt -r api/requirements-api.txt
export MARSWALK_GRID=data/processed/grid5m     # if your grid is elsewhere
uvicorn api.main:app --reload
```

Interactive docs at `/docs`. About 10 s to start, about 0.3 s per route, about
470 MB of memory.

## Endpoints

`POST /api/routes/fastest`, `/easiest`, `/pareto`, `/mineral-target`,
`/time-budget`, `/via-shelter` · `POST /api/emergency/reachable` ·
`GET /api/health`, `/api/scientific-destinations`, `/api/terrain/layers`,
`/api/terrain/point`

A position can be a waypoint id, east/north metres from the habitat, or lat/lon.
Positions outside the exported window (about ±1.37 km from the habitat) return
422, never an estimate.

## Which file to read

| File | What it is |
|---|---|
| `API_CONTRACT.md` | The contract the endpoints implement: paths, request and response shapes, error behaviour |
| `README_API_LIVE.md` | The build and deployment notes: test results, how to deploy to Cloud Run, and what is still missing |
| `README_API.md` | The brief this service was written from |
| `openapi.json` | The generated OpenAPI schema |
| `examples/` | Example requests |
| `engine.py` | Loads the terrain once and calls `routing.export_handoff.Exporter`, so the API and the saved files share one source of numbers |
| `main.py` | The FastAPI app: endpoints, validation, CORS |

Deploy with `tools/deploy_cloud_run.sh`, which also runs `tools/check_live_api.py`
(44 live checks) against the new URL.
