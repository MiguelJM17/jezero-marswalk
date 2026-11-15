"""Jezero Marswalk routing API (FastAPI), following API_CONTRACT.md v1.

Run locally:  uvicorn api.main:app --port 8080
"""
import copy
import os
import traceback
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from routing import config as C

from .engine import GRID_NAME, HABITAT_LAT, HABITAT_LON, HANDOFF_DIR, ApiError, Engine

ENGINE: Optional[Engine] = None


def engine() -> Engine:
    global ENGINE
    if ENGINE is None:
        ENGINE = Engine()
    return ENGINE


@asynccontextmanager
async def lifespan(app):
    engine()  # load Area + Planner once at startup
    yield


app = FastAPI(title="Jezero Marswalk routing API", version="1.0",
              description="Routes for astronauts walking in Jezero crater, Mars. Same JSON as outputs/. "
                          "relative_effort is in hours of suit supply at 1200 BTU/h (model, not verified); "
                          "oxygen_verified is always false.",
              lifespan=lifespan)

ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "https://marseva.us,https://www.marseva.us,https://jolly-mars-path-pilot.base44.app").split(",")
           if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["GET", "POST", "OPTIONS"],
                   allow_headers=["*"])
_layers = os.path.join(HANDOFF_DIR, "map_layers")
app.mount("/static/map_layers", StaticFiles(directory=_layers), name="map_layers")
app.mount("/map_layers", StaticFiles(directory=_layers), name="map_layers_compat")


# ---------------------------------------------------------------- errors: {"error", "detail"}
def err(status, code, detail):
    return JSONResponse(status_code=status, content={"error": code, "detail": detail})


@app.exception_handler(ApiError)
async def _api_error(request, e: ApiError):
    return err(e.status, e.code, e.detail)


@app.exception_handler(RequestValidationError)
async def _validation(request, e: RequestValidationError):
    msgs = "; ".join(f"{'.'.join(str(x) for x in d.get('loc', []))}: {d.get('msg')}" for d in e.errors())
    return err(422, "invalid_request", msgs)


@app.exception_handler(StarletteHTTPException)
async def _http(request, e: StarletteHTTPException):
    return err(e.status_code, "not_found" if e.status_code == 404 else "http_error", str(e.detail))


@app.exception_handler(Exception)
async def _any(request, e: Exception):
    traceback.print_exc()
    return err(500, "internal_error", f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------- request bodies
class RouteReq(BaseModel):
    to: dict
    from_: Optional[dict] = Field(None, alias="from")
    round_trip: bool = True
    dwell_min: float = Field(C.DEFAULT_DWELL_MIN, ge=0)
    model_config = {"populate_by_name": True}


class MineralReq(BaseModel):
    mineral: str
    from_: Optional[dict] = Field(None, alias="from")
    dwell_min: float = Field(C.DEFAULT_DWELL_MIN, ge=0)
    model_config = {"populate_by_name": True}


class BudgetReq(BaseModel):
    time_budget_min: float = Field(..., gt=0)
    from_: Optional[dict] = Field(None, alias="from")
    dwell_min: float = Field(C.DEFAULT_DWELL_MIN, ge=0)
    multi_stop: bool = True
    model_config = {"populate_by_name": True}


class EmergencyReq(BaseModel):
    position: dict
    suit_supply_left_h: float = Field(..., ge=0)
    reserve_fraction: float = Field(C.EMERGENCY_MARGIN, ge=0, lt=1)


def run(fn, *args):
    E = engine()
    with E.lock:  # the Planner caches graphs in a dict: one request at a time
        return fn(*args)


# ---------------------------------------------------------------- endpoints
@app.get("/api/health")
@app.get("/health", include_in_schema=False)
def health():
    engine()
    return {"ok": True, "grid": GRID_NAME, "habitat": {"lat": HABITAT_LAT, "lon": HABITAT_LON}}


@app.post("/api/routes/fastest")
def fastest(req: RouteReq):
    r = run(engine().single, req.from_, req.to, "fastest", req.round_trip, req.dwell_min)
    return {"routes": [r], "oxygen_verified": False}


@app.post("/api/routes/easiest")
def easiest(req: RouteReq):
    r = run(engine().single, req.from_, req.to, "easiest", req.round_trip, req.dwell_min)
    return {"routes": [r], "oxygen_verified": False}


@app.post("/api/routes/pareto")
def pareto(req: RouteReq):
    rs = run(engine().pareto, req.from_, req.to, req.round_trip, req.dwell_min)
    return {"routes": rs, "oxygen_verified": False}


@app.post("/routes", include_in_schema=False)
def routes_compat(req: RouteReq):
    """Fastest / balanced / easiest, as in routes.json."""
    rs = run(engine().pareto, req.from_, req.to, req.round_trip, req.dwell_min, (1.0, 0.5, 0.0))
    return {"routes": rs, "oxygen_verified": False}


@app.post("/api/routes/via-shelter")
def via_shelter(req: RouteReq):
    """Extra (not in API_CONTRACT.md v1): round trip that passes by the best terrain shelter,
    like the via_shelter routes in routes.json. Always a round trip."""
    r = run(engine().via_shelter, req.from_, req.to, req.dwell_min)
    return {"routes": [r], "oxygen_verified": False}


@app.post("/api/routes/mineral-target")
def mineral_target(req: MineralReq):
    rs = run(engine().mineral_target, req.mineral, req.from_, req.dwell_min)
    return {"routes": rs, "oxygen_verified": False}


@app.post("/api/routes/time-budget")
def time_budget(req: BudgetReq):
    single, best = run(engine().time_budget, req.time_budget_min, req.from_, req.dwell_min, req.multi_stop)
    return {"single_stop": single, "best_tour": best, "oxygen_verified": False}


@app.post("/api/emergency/reachable")
def emergency(req: EmergencyReq):
    return run(engine().emergency, req.position, req.suit_supply_left_h, req.reserve_fraction)


@app.get("/api/scientific-destinations")
def destinations():
    E = engine()
    d = copy.deepcopy(E.waypoints_doc)
    d["mineral_patches"] = copy.deepcopy(E.minerals_doc["minerals"])
    d["mineral_patches_note"] = E.minerals_doc.get("note")
    return d


def _public_base(request: Request):
    base = str(request.base_url).rstrip("/")
    proto = request.headers.get("x-forwarded-proto")
    if proto and base.startswith("http://") and proto == "https":
        base = "https://" + base[len("http://"):]
    return base


@app.get("/api/terrain/layers")
def layers(request: Request):
    m = copy.deepcopy(engine().manifest)
    base = _public_base(request)
    for L in m["layers"]:
        L["file"] = f"{base}/static/{L['file']}"
    return m


@app.get("/api/terrain/point")
def terrain_point(east_m: Optional[float] = Query(None), north_m: Optional[float] = Query(None),
                  lat: Optional[float] = Query(None), lon: Optional[float] = Query(None)):
    pos = {"east_m": east_m, "north_m": north_m, "lat": lat, "lon": lon}
    return run(engine().point, pos)
