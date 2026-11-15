# Jezero Marswalk — Euler's Disappointments

**Google Maps tells you how to get there. We also tell you whether you can make it back.**

NASA Space Apps Challenge 2026 · Team **Euler's Disappointments** · Challenge: a layered map to plan a Marswalk.

[![tests](https://github.com/MiguelJM17/jezero-marswalk/actions/workflows/tests.yml/badge.svg)](https://github.com/MiguelJM17/jezero-marswalk/actions/workflows/tests.yml)

**Jump to:** [What the engine computes](#what-the-engine-computes) · [Method](#method) · [Validation against Perseverance's real path](#validation-against-perseverances-real-path-and-what-it-does-not-prove) · [What we do not know](#what-we-do-not-know-and-say-so) · [Repository layout](#repository-layout) · [Reproduce](#reproduce) · [NASA data](#nasa-data-and-resources)

Jezero Marswalk plans walks for an astronaut on foot in Jezero crater, Mars. It turns NASA orbital and rover data into decisions:

- **"I want to go to this mineral."** Pick probable carbonate, olivine or clay and get every route there and back, each with distance, time and effort.
- **"I have this much time."** Get the stops that fit in 1 to 8 hours, and the order to visit them.
- **Emergency.** Lost comms or a broken part? See which shelters, communication points or the habitat you can still reach with the suit supply you have left, keeping a reserve.
- **Stop photos.** Real Perseverance photos at each stop, with the mineral and the MEDA pressure measured there.

**See it: https://marseva.us** — a front end built on Base44 to look around the crater and compare the routes. It reads the precomputed files in `outputs/`, so it is a way to visualise what the engine produced rather than the full system described below.

---

## What the engine computes

| | |
|---|---|
| Site | Jezero crater; habitat at 18.452739° N, 77.405768° E (flat ground, 1.4° slope) |
| Terrain model | 5 m grid built from the 1 m HiRISE DTM, THEMIS thermal inertia and the CRISM mineral map |
| Missions used | Four: MRO (HiRISE, CRISM), Mars Odyssey (THEMIS), Mars 2020 (traverse, Mastcam-Z, Navcam, MEDA) and MSL (Curiosity RAD) — eight data products |
| Science stops | 6 probable mineral sites (2 olivine, 2 carbonate, 2 clay/kaolinite), all within 574 m of the habitat and near Perseverance's real path |
| Routes | 28 precomputed routes: fastest, easiest and Pareto alternatives to every stop (always round trip), 5 time-budget tours, 6 routes that pass by a shelter |
| Safety | No point of any route is more than **7.5 min** from the habitat or a terrain shelter, and no more than **12.5 min** from the habitat alone |
| Full tour | All 6 stops: **2.74 km, 3 h 57 min** (57 min walking + 6 × 30 min of science), within the 6 h recommended EVA |

| Destination (round trip) | Distance | Total time (incl. 30 min science) | Steepest walking grade | Steepest ground under the route |
|---|---|---|---|---|
| Clay stops | 489–540 m | 38–39 min | 2.0–2.8° | 2.6–3.5° |
| Olivine stops | 1127–1257 m | 50–52 min | 7.2–8.6° | 10.0–12.1° |
| Carbonate stops | 1163–1242 m | 58–60 min | 21.8–28.0° | 33.4–39.5° |

The carbonates sit on top of an escarpment: their routes cross 34–40° ground diagonally, so the
walking grade stays at 28° or less. That diagonal has a side slope, and **neither Tobler nor
Pandolf models side slope**, which is where falls happen: both were measured walking straight up
or down. Both equations are also being applied well outside the grades they were measured on.

So we measure it. A step across a hillside splits the terrain's steepest slope into the grade
along the direction of travel and the side slope across it,
`tan(terrain)² = tan(grade)² + tan(side)²`, which follows from data already on the grid. Every
route and segment reports `max_side_slope_deg` and `m_side_slope_steeper_than_20deg`. The
carbonate routes reach **27.8°** of side slope, with 26 m above the 20° reference.

`SIDE_SLOPE_WEIGHT` in `routing/config.py` can also price it, by adding a fraction of the side
slope to the grade Pandolf sees. It ships at **0**, which measures without pricing, because no
measurement exists for a suited astronaut traversing a Martian hillside and the weight would be
ours. What the weight would change is measured rather than guessed:

| `SIDE_SLOPE_WEIGHT` | Tour distance | Worst side slope | Metres above 20° side slope, all 28 routes | Metres above 20° ground |
|---|---|---|---|---|
| **0 (shipped)** | 2740 m | 27.8° | 570 | 1553 |
| 0.25 | 2739 m | 15.4° | 215 | 1036 |
| 0.5 | 2765 m | 12.6° | 210 | 999 |
| 1.0 | 2820 m | 10.4° | 205 | 972 |

The useful part is not the number we would pick. It is that **the benefit arrives at 0.25 and then
flattens**: any penalty at all removes about 62% of the side-slope exposure, the first quarter of
it costs no distance at all (2740 m against 2739 m), and raising the weight to 1.0 buys 10 more
metres for 3% more walking. The conclusion does not depend on the coefficient, which is the usual
objection to assuming one. The validation section below gives the empirical anchor the weight
otherwise lacks: Perseverance crossed this same ground without once exceeding 20° of side slope,
and a weight of 0.5 brings our routes inside that envelope. Anything above 20° is reported as a **warning** (team decision), never
silently hidden.

## Method

1. **Common grid.** All layers are resampled to the same 5 m grid in the DTM's equirectangular projection (Mars 2000 sphere, R = 3,396,190 m). Ground east distance is corrected by cos(latitude) (×0.948 at Jezero). Roughness is the standard deviation of the 1 m slope inside each 5 m cell, which keeps rough ground from being flattened by averaging. A HiRISE DTM resolves detail coarser than its 1 m posting, so boulders of a metre or two are still invisible to it.
2. **Graph.** Each cell is a node connected to its 8 neighbours. Edges are directed, because uphill costs more than downhill. Forbidden cells (no edge) are cells without elevation, thermal inertia below 100 (possibly not load-bearing; none in this area) and a DTM artefact strip west of lon 77.35° E (our assumption; far from the area).
3. **Time.** Tobler's hiking function, scaled so that flat ground gives 3.6 km/h, the Apollo planners' walk-back speed.
4. **Effort.** Pandolf's metabolic equation (no load), with a terrain factor from roughness and soft soil (thermal inertia). Downhill is counted as flat grade **in the effort weight only**: `DOWNHILL_MIN_REL` switches that clamp on, but it is not a floor on the rate, and the metabolic rate can still fall below flat on a descent, to 0.62 at a 30% grade, because the speed term shrinks. The effort of a step never falls below that of a flat step of the same horizontal length, which we checked by sweeping the grades, but that holds because Tobler lengthens the time enough to compensate, not because of the clamp. The time weight is Tobler's curve unmodified, which is fastest on a gentle descent, as walking actually is. Effort is expressed in **hours of suit supply at 1200 BTU/h**: a model estimate, **not verified for Mars**.
5. **Search.** Dijkstra's algorithm (scipy.sparse.csgraph) on about 2.5 million edges. The fastest route minimises time, the easiest minimises effort, and sweeping a blend of the two weights gives non-dominated alternatives. Sweeping a linear blend only reaches the convex hull of the trade-off curve, so these are non-dominated routes found by that sweep, not the complete Pareto front. Multi-stop order is an exhaustive search. Emergency mode is one Dijkstra from the astronaut's position, filtered by the usable suit supply (25% reserve, team assumption).
6. **Shelters and comms.** Shelters are walkable cells (≤ 20°) where the terrain hides the most sky, using horizon angles over 500 m in 16 directions: a geometric proxy, not a life-support shelter. A communication point is a walkable cell with a straight line of sight to a 3 m antenna at the habitat, with the suit antenna at 1.8 m (assumed heights).

All constants live in [`routing/config.py`](routing/config.py), each labelled **SOURCED** (with its reference) or **ASSUMPTION**.

## Validation against Perseverance's real path, and what it does not prove

We compared our routes with NASA's `M20_traverse.json` (Perseverance's actual drives, sols 401–762 in this area).

![Our routes vs Perseverance's path](docs/validation/routes_vs_rover.png)

Between 77 and 100 percent of each route to the clay and carbonate stops stays within 100 m of the rover's
path, and the route to clay 1 runs on top of it (16 m on average). **On its own that number proves nothing**,
because the stops were chosen near the rover's path in the first place. So we measured the baseline: a
straight line drawn from the habitat to the same stop, ignoring the terrain completely.

| Stop | straight line, % within 100 m | our fastest route, % within 100 m |
|---|---|---|
| clay_01 | 100.0 | 100.0 |
| clay_02 | 83.7 | 85.2 |
| carbonate_01 | 91.5 | 83.3 |
| carbonate_02 | 91.2 | 87.7 |
| olivine_01 | 68.2 | 63.4 |
| olivine_02 | 64.9 | 63.4 |
| **mean** | **83.3** | **80.5** |

A straight line scores slightly better than our routes. The honest reading is that this comparison is a
**sanity check, not a validation of route quality**: it shows our routes stay mostly inside the corridor
Perseverance actually crossed. It does not
show the routes are good, and we do not claim that it does.

The same script measures the slope profile of both. Our routes are 4–13 percent longer than the straight
line, and on the two carbonate stops they cross **more** ground above 20°, not less (65 m against 45 m, and
100 m against 55 m). That is the cost model behaving as designed rather than a defect: it trades a gentler
walking grade for a longer diagonal across the escarpment. It is also the clearest argument for the
calibration loop described below, because no measurement exists to say which of those two trades a suited
astronaut should prefer.

Part of the extra length is not the cost model at all. An 8-connected grid can only travel in multiples
of 45°, so reaching a point on an intermediate bearing requires a staircase, which adds up to 8.2% in the
worst case (a bearing 22.5° off the axis). The clay routes show it: they cross nearly flat ground and
still come out about 4% longer than the straight line. Separating grid quantisation from genuine terrain
avoidance needs a 16-connected grid or path smoothing. Until then, the 4–13% figure is an **upper bound**
on how much of the detour the cost model is responsible for.

### What Perseverance itself accepted

The same script measures side slope on the ground the rover actually drove inside this window.
Perseverance's own path reaches **21.0°** of ground slope, 10 m of it above 20°, and a maximum
side slope of **17.7°** with **not one metre above 20°**. Our carbonate routes put a walking
astronaut on 32.4° and 35.1° of side slope.

A six-wheeled vehicle built for rough ground, with a far wider stance than a person on foot,
stayed inside 20° of cross-slope everywhere it went here. That is not proof of what a suited
human can take, and the rover chose its path for science and wheel safety rather than for human
effort. But it is the only traverse of this terrain that has actually happened, and our routes
sit well outside the envelope it kept to. Of everything in this section, this is the finding we
would act on first.

Reproduce both tables: `MARSWALK_GRID=<grid> python3 docs/validation/baseline_check.py`
(output saved in `docs/validation/baseline_check.txt`). The per-route distance table is
[`docs/validation/route_vs_rover.csv`](docs/validation/route_vs_rover.csv).

## Why this scales

Nothing in the engine knows it is looking at Jezero. It reads a raster, builds a
graph of cells, and runs Dijkstra. Every property below was checked against the
code in this repository, not assumed.

**More resolution is a flag, not a rewrite.** Cell size is `build_grid.py --res`.
We ran 5 m; the default is 10 m and the source DTM is 1 m. The same command
builds any of them, and nothing downstream is told which one it got: the planner
reads the cell size out of `grid.json`.

**More area costs close to linear time.** The grid we build already spans
4,280 x 4,297 cells. Because ground east distance is corrected by cos(latitude),
a cell is 4.74 m east by 5.0 m north on the ground, so the grid covers
20.3 x 21.5 km, about 18.4 million cells. The routes in
this submission are computed in a 3 x 3 km window around the habitat, roughly
310,000 walkable cells and 2.5 million directed edges -- a crop of the grid, not
the engine's ceiling. Dijkstra over an 8-connected grid has about eight edges
per cell, so the work grows with the number of cells rather than exploding with
the size of the map, and scipy's implementation returns the exact optimum, never
an approximation that degrades as the map grows.

**Another site is another file.** `build_grid.py` reads the projection, the
origin and the pixel size out of the DTM itself; nothing about the coordinate
system is written into the code. Point it at a DTM of Gale, of the lunar south
pole, of anywhere with elevation data, give it a base latitude and longitude,
and the same pipeline produces the same outputs. Layers that are missing simply
drop out of the cost model instead of breaking it.

**Better numbers are a config edit.** `routing/config.py` carries 29 constants,
each marked SOURCED with its reference or ASSUMPTION with its reason.
When a real Mars EVA duration, a measured walking speed or a true suit
consumption rate is published, it replaces one labelled line. No equation in the
planner changes, and the tests immediately show what moved.

**More data makes the answers better, not just bigger.** The route alternatives
come from blending the cost weights and keeping the non-dominated results, so
every new layer adds a dimension the astronaut can trade against the others.
Today the blend runs over time, effort, terrain and shelter proximity. Add dust
opacity, surface temperature at the hour of the walk, or a measured soil
bearing-strength map, and the same Pareto step yields richer alternatives
without a line of new search code. The validation improves the same way: every
additional sol of rover traverse is more ground truth to check the routes
against.

**Any point, not six.** The saved files hold 28 precomputed routes because the
front end reads files. The API in `api/` computes a route to an arbitrary
coordinate on demand, and it is already tested that way. That is a deployment
step, not new mathematics.

**The loop that closes it: measured walks.** Every number this engine produces
rests on a model that has never been walked. Tobler's curve is from terrestrial
hikers, Pandolf's equation from loaded soldiers on Earth, the 1200 BTU/h rate
from EVA planning; `routing/config.py` labels more than half of its 29 constants ASSUMPTION
for exactly this reason. The app already keeps a trip log: the astronaut saves a
route they chose and it stays on their record. **Today that log lives only in the
browser and is not read back.** The step it exists for is to record what actually
happened next to what was predicted -- the time the walk really took, the supply
really used, where the ground was softer or firmer than the thermal inertia
suggested -- so that each ASSUMPTION constant can be replaced by a measurement
from the surface it was guessed for, and the residual between predicted and
observed becomes a training signal rather than a footnote. That is the point at
which a terrain cost model stops being a planning aid and starts being
calibrated. The architecture is already shaped for it: the model is isolated in
one labelled config file, the engine reads it, and the tests pin every route to
the engine, so a corrected constant propagates everywhere and any drift shows up
immediately. What is missing is the recording of the actual walk, not the way
the model would consume it.

**Where it does not scale yet, and the fix.** Multi-stop ordering is an
exhaustive search over subsets and permutations (`itertools.permutations` in
`routing/planner.py`). It is exact and it is fine for the 6 stops here, but it
is factorial: somewhere past roughly ten stops it becomes the bottleneck, long
before the terrain grid does. The replacement is standard -- dynamic programming
over subsets, which is exponential in stops instead of factorial and handles
tens of stops comfortably. Everything else in the pipeline is already
independent of how many stops there are.

## What we do not know (and say so)

- Minerals are **probable** orbital detections (CRISM), not confirmed samples.
- Oxygen use is a **model estimate** (`oxygen_verified: false` everywhere).
- Slope, duration and radius limits (20°, 6/8 h, 2 km) are NASA **Artemis** planning references; no official Mars values exist.
- Radiation is a **reference** value measured by Curiosity RAD in **Gale crater**, not in Jezero (median 130 µGy/day over the last 30 days of data).
- MEDA has **no published wind** data after sol 315, so we show pressure only.
- Stop photos come from the nearest rover position, 48–294 m away; the camera direction is not confirmed.

**Supply while standing (fixed).** `relative_effort` counted walking only, so a route with a
30 minute science stop understated what the suit spends. Pandolf with V = 0 leaves the standing
term alone, which is exactly half the flat walking rate, so `standing_rel()` derives 0.5 from the
constants already in `config.py` rather than adding one. Every route now carries
`supply_h_walking`, `supply_h_science`, `supply_h_total` and `supply_pct_of_suit`. Counting the
stops multiplies the old figures by 1.6 on average: the six-stop tour goes from 1.49 h to
**2.99 h, 37% of an 8 h suit**, and the worst single round trip reaches 13%. No route changed
feasibility, since the 6 h and 8 h flags are time-based and time always included the stops.
Emergency mode is unaffected: an emergency walk has no science stops. The 0.5 rate is still a
**lower bound**, because sampling and handling tools cost more than standing still.

## Radiation estimate

Each route carries `radiation_dose_estimate_uGy`, and each shelter a dose rate and its saving against open sky (18–21%). The model scales the dose by the fraction of sky the terrain hides, which treats the sky as uniformly bright. The sky a ridge hides is near the horizon, and radiation arriving from there crosses more atmosphere, so the real saving is **at most** that fraction. These are partial shelters: a fifth less dose, not a safe room. The estimate is walking time × the Curiosity RAD median rate (5.42 µGy/h) × (1 − fraction of sky hidden by terrain). For example, the full 6-stop tour is about 4.8 µGy while walking. This is a **comparison tool, not a dose prediction**: the rate was measured in Gale crater, and terrain shielding is approximated geometrically (see `outputs/route_model.json` → `radiation`).

## Routing API (status: built and tested locally, not deployed yet)

A FastAPI service wraps the same routing engine. It is **not connected to the live app**: marseva.us reads the saved files in `outputs/`, so it can only show the routes that were computed ahead of time. The API is the piece that would let the app ask for a route to any point; it runs and passes its tests, but it is not deployed. Valeria built the first version; Ronald finished it on the current engine. Every number comes from `routing.export_handoff.Exporter`, so the API and the saved files share one source.

- **Endpoints:** `POST /api/routes/fastest`, `/easiest`, `/pareto`, `/mineral-target`, `/time-budget`, `/via-shelter`; `POST /api/emergency/reachable`; `GET /api/health`, `/api/scientific-destinations`, `/api/terrain/layers`, `/api/terrain/point`. A position can be a waypoint id, east/north metres from the habitat, or lat/lon. Docs at `/docs`.
- **Tests:** 52 pass (14 engine tests + 38 API tests), on Python 3.13 and 3.10 (the Dockerfile version). All 28 saved routes and all 4 emergency scenarios come out identical, field by field, from the live API; a test fails if any saved route is left unchecked.
- **Coverage:** the exported map window, about ±1.37 km from the habitat. Unknown or out-of-bounds positions return an error (422), never an estimate.
- **Performance:** about 10 s to start, about 0.3 s per route, about 360 MB of memory.
- **Deploy:** `REGION=<region> bash tools/deploy_cloud_run.sh` deploys to Cloud Run and runs `tools/check_live_api.py` (44 live checks) against the new URL.
- **Not done yet:** Cloud Run deployment and connection to the Base44 app. Until then the app uses the precomputed files in `outputs/`, which stay as the fallback.

## Use of AI tools

The project idea, challenge choice, site, stops and every design decision (cost model, slope warnings instead of bans, what counts as a shelter or a comms point) are the team's. We used an AI assistant (Anthropic's Claude) to help write and debug the Python processing and routing code in this repository, to process and check the data files, to draft documentation, and to edit the text of this submission. The routing API (`api/`, `tests/test_api.py`, `tools/`) was written by Ronald with the help of Claude (Anthropic); he directed the work and ran the checks, and the 52 tests compare every answer with the engine-generated files. Valeria's earlier adapter was built with help from OpenAI Codex. The front end at marseva.us was built on Base44, which is itself an AI app builder: we specified the behaviour and the data it reads, and it generated the interface code. Every number in the outputs comes from running this code on the NASA data listed below. Rover photos, positions and the validation were selected and checked by the team.

## What is in this repository

The engine, the data pipeline, the routing API and the outputs they produce. The front end at marseva.us was built on Base44, which does not let us export its source, so it is not here. Everything the front end displays does come from this repository: the JSON files and map layers in `outputs/`.

## Repository layout

The pipeline runs left to right. NASA rasters become one grid, the grid becomes a
graph, the graph produces routes, and the routes are written out as JSON the app reads.

```
data/            processing/      routing/                    outputs/
NASA rasters  →  build_grid.py →  terrain.py → planner.py  →  JSON + map layers
(not committed)  (one 5 m grid)   (graph)      (Dijkstra)      (the output)
                                      ↑                            ↓
                                  curated/                       api/
                            (stops, rover positions,        (serves the same
                             photo table: team-made)          objects live)
```

### Folders

| Path | What it is |
|---|---|
| `processing/` | Turns the raw NASA files into the shared grid. `build_grid.py` writes the 5 m rasters; `meda_summary.py` summarises MEDA pressure; `rad_summary.py` reduces 315 RAD files to one dose rate; `check_grid.py` draws a quick-look figure of every layer |
| `routing/` | The engine. `config.py` (every constant with its source), `terrain.py` (reads the grid, sky view, line of sight), `planner.py` (graph, Dijkstra, alternatives, tour, emergency), `export_handoff.py` and `export_grid.py` (write the outputs), `run_plan.py` and `plot_plan.py` |
| `curated/` | The inputs the team compiled by hand: the 6 science stops, Perseverance positions, the photo table and the MEDA file index. Its `README.md` is the key to the Spanish column names |
| `outputs/` | **The output.** Nine JSON files and eight map layers, generated by `routing/export_handoff.py`. Nothing here is typed by hand. Opens with its own `README.md` |
| `api/` | The routing API (FastAPI) that serves the same objects live, plus its contract, its deployment notes and `openapi.json` |
| `tests/` | 14 engine tests on synthetic terrain, 38 API tests against the saved outputs |
| `docs/` | Validation figure and tables, photo and MEDA notes, and the prompt used to build the front end |
| `tools/` | Deployment script and the 44 live checks run against a deployed API |
| `scripts/` | `download_rad.sh`, which fetches the Curiosity RAD files from CDAWeb |
| `data/` | Where the downloaded NASA rasters go. Only the small MEDA summary is committed; the rest is too large for GitHub (see "Reproduce") |

### Files at the root

| File | What it is |
|---|---|
| `README.md` | This file |
| `requirements.txt` | Python dependencies |
| `Dockerfile` | Builds the API container for Cloud Run |
| `LICENSE` | MIT, for the code |
| `NOTICE` | What the MIT license does not cover: the NASA data, credited with its sources in this file |
| `.gitignore` | Keeps the large NASA rasters, the RAD files and build artefacts out of the repository |
| `.dockerignore`, `.gcloudignore` | Keep tests, processing scripts and source data out of the deployed container, so the image only carries what the API needs |

## Reproduce

Everything below runs from a clone of this repository, with no files from us
beyond what is committed here. The NASA source data is downloaded in step 1.

```bash
pip install -r requirements.txt            # engine, processing, engine tests
pip install -r api/requirements-api.txt    # only for the API and its tests (step 5)
```

1. **Download the source data** into `data/` (not committed; too large):
   - HiRISE DTM: USGS Mars 2020 TRN HiRISE DTM mosaic, https://doi.org/10.5066/P9REJ9JN
     (direct file: https://planetarymaps.usgs.gov/mosaic/mars2020_trn/HiRISE/JEZ_hirise_soc_006_DTM_MOLAtopography_DeltaGeoid_1m_Eqc_latTs0_lon0_blend40.tif)
   - THEMIS thermal inertia: https://zenodo.org/record/4931348 (`Jezero_Thermal_Inertia_v1.tiff`)
   - CRISM mineral map: https://zenodo.org/record/5575824 (`jezeroFinal.tif` and its legend)
   - Curiosity RAD: `bash scripts/download_rad.sh`
   - MEDA PS files: see `curated/meda_files.csv`, then `python3 processing/meda_summary.py meda/*.CSV > data/meda_pressure_summary.json`
2. **Build the grid:** `python3 processing/build_grid.py --res 5 --strip 100`
3. **Export everything the app needs (about 10–20 s, about 360 MB RAM).** If you built the grid somewhere other than `data/processed/grid5m`, add `--grid <folder>`. The RAD files must be in `data/rad` (step 1); without them the export still runs but has no radiation fields. Rover positions come from `curated/rover_waypoints_minerals.csv`.
   ```bash
   python3 -m routing.export_handoff --stops curated/proposed_stops.csv --photos curated/photo_table.csv \
       --option A --base-lat 18.452739 --base-lon 77.405768 --out outputs
   ```
4. **Export the terrain grid the front end draws under the routes.** `export_handoff.py` writes the
   routes and the map layers; this writes the elevation grid itself, which the app loads separately.
   ```bash
   python3 -m routing.export_grid --base-lat 18.452739 --base-lon 77.405768 \
       --half 1400 --cell 10 --out outputs/terrain_grid_10m.json
   ```
   The file is committed (2.3 MB), so steps 3 and 4 only rebuild what is already here. Together
   they produce every file the front end reads.
5. **Tests:** `python3 -m pytest -q tests` — 52 tests (14 engine, 38 API). The 14 engine tests run
   on synthetic terrain and need nothing from steps 1 to 4, so they pass on a fresh clone with only
   `requirements.txt` installed; the 38 API tests are skipped, with the reason printed, until
   `api/requirements-api.txt` is installed. Those 38 also need the grid from step 2, because the API
   loads the real terrain at startup. If your grid is not at `data/processed/grid5m`, point to it
   first: `export MARSWALK_GRID=/path/to/grid5m`.

All of the above was run end to end from a clean clone on 15 November 2026: `pip install`, both
exports with the commands exactly as written, and 52 tests passing.

## NASA data and resources

- USGS Astrogeology — Mars 2020 TRN HiRISE DTM mosaic: https://doi.org/10.5066/P9REJ9JN
- THEMIS-derived thermal inertia of Jezero (Mars Odyssey; Edwards et al.): https://zenodo.org/record/4931348
- CRISM mineral map of Jezero (MRO; Parente, Itoh & Saranathan): https://zenodo.org/record/5575824
- Perseverance waypoints: https://mars.nasa.gov/mmgis-maps/M20/Layers/json/M20_waypoints.json
- Perseverance traverse: https://mars.nasa.gov/mmgis-maps/M20/Layers/json/M20_traverse.json
- Perseverance raw images (Mastcam-Z: NASA/JPL-Caltech/ASU; Navcam: NASA/JPL-Caltech): https://mars.nasa.gov/mars2020/multimedia/raw-images/
- MEDA derived pressure, PDS Atmospheres Node (Rodriguez-Manfredi et al. 2021, https://doi.org/10.17189/1522849): https://atmos.nmsu.edu/PDS/data/PDS4/Mars2020/mars2020_meda/data_derived_env/
- Curiosity RAD Level 2, NASA CDAWeb: https://cdaweb.gsfc.nasa.gov/sp_phys/data/msl/rad/cdf/obs-l2/
- Apollo Lunar Surface Journal (3.6 km/h walk-back speed): https://www.nasa.gov/history/alsj/
- Pandolf equation used for EVA workload, NASA NTRS 20240001423: https://ntrs.nasa.gov/citations/20240001423
- NASA Exploration EVA testing and analogs (Coan 2021; 20° slope, 8 h EVAs), NTRS 20210000827: https://ntrs.nasa.gov/citations/20210000827
- Exploration EVA Concept of Operations, EVA-EXP-0075 (2 km radius)
- Fergason et al. 2012, Space Science Reviews (thermal inertia below 100), doi:10.1007/s11214-012-9891-3
- 1200 BTU/h EVA planning rate: ICES-2026-127

## Team

Euler's Disappointments — Miguel Jazzan · Ronald Aguirre · Marilennis Naranjo · Valeria Calagna · Samantha Miranda · Rania Jazzan
