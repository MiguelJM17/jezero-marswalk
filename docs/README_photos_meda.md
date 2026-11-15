# Perseverance photos and MEDA pressure — data notes

Part of **Euler's Disappointments — Jezero Marswalk** (route planner for an astronaut on foot in Jezero crater).
Author of this part: Ronald Aguirre. Last updated: Nov 14, 2026.

This document explains where the stop photos and the weather data come from, how they were selected and checked, and what they cannot tell you.

## 1. Rover positions
- **Source:** NASA's Mars 2020 rover waypoints file, the same data behind the "Where is Perseverance?" map: <https://mars.nasa.gov/mmgis-maps/M20/Layers/json/M20_waypoints.json>. Each record has the sol, planetocentric latitude, east longitude, elevation and the rover motion counter (`site_drive`, for example `24_3290`).
- **Filter:** end-of-drive localizations inside the study box (lat 18.3068–18.6693, lon 77.2229–77.584). Mid-drive and interpolated points were dropped. This leaves 521 positions, of which 356 are east of lon 77.30; the positions west of that line are on the crater rim.
- **Alignment check:** for all 356 points, DTM elevation minus rover elevation has a median of 0.0 m and a spread of 0.2 m, so the waypoint coordinates and the team grid agree.

## 2. Stop selection (summary)
Each rover position was sampled on the team's 10 m mineral layers (CRISM classes and confidence), using a 3×3 window. A stop had to meet all of these:
- high-confidence pixel of its mineral group;
- inside a patch of at least 10 cells;
- at least 7 of its 9 neighbourhood cells in the same group;
- inside DTM coverage, and east of lon 77.30;
- a rover position within 300 m, so that photos exist.

Mineral groups: olivine = class 1, carbonate = class 2, clay = classes 3, 9 and 10. The clay stops in the final set are kaolinite (class 9). All minerals are **probable** orbital detections, not confirmed samples.

Distances are great-circle distances on the Mars 2000 sphere (R = 3,396,190 m), cross-checked with `pyproj.Geod` (differences under 1.5 m).

## 3. Photos (12, two per stop)
- **Source:** NASA's official Mars Perseverance raw-image gallery, <https://mars.nasa.gov/mars2020/multimedia/raw-images/>. Each `image_url` is the full-resolution PNG behind the page's "Download" button.
- **Position check:** a photo is used only if its `site` and `drive` match the rover position assigned to the stop. This was checked twice: through the gallery filter, and against the code embedded in the image ID (for example, `N0243290` means site 24, drive 3290).
- **Content check:** every candidate frame was reviewed by eye. Only landscape views were kept (horizon, terrain or outcrops); frames of the rover arm, wheels, deck, sky, the Sun and rock close-ups were rejected. One Mastcam-Z frame (colour, left camera, RGB filter) and one full-frame Navcam frame (left camera) were kept per stop.
- **Credits** are copied from each photo's page: Mastcam-Z "NASA/JPL-Caltech/ASU"; Navcam "NASA/JPL-Caltech".

| Stop | Sol | Camera | Date (UTC) | Rover `site_drive` | Photo position → stop | Credit | Page | File |
|---|---|---|---|---|---|---|---|---|
| `olivine_01` | 416 | Mastcam-Z (left) | 2022-04-22 | `23_1180` | 275 m | NASA/JPL-Caltech/ASU | [page](https://mars.nasa.gov/mars2020/multimedia/raw-images/ZL0_0416_0703883351_706EBY_N0231180ZCAM08433_1100LMJ) | `sol0416_mastcamz_olivine_01.png` |
| `olivine_01` | 417 | Navcam (left) | 2022-04-23 | `23_1180` | 275 m | NASA/JPL-Caltech | [page](https://mars.nasa.gov/mars2020/multimedia/raw-images/NLF_0417_0703951757_886ECM_N0231180NCAM12416_01_195J) | `sol0417_navcam_olivine_01.png` |
| `olivine_02` | 420 | Mastcam-Z (left) | 2022-04-26 | `23_2532` | 294 m | NASA/JPL-Caltech/ASU | [page](https://mars.nasa.gov/mars2020/multimedia/raw-images/ZL0_0420_0704214283_149EBY_N0232532ZCAM08441_0630LMJ) | `sol0420_mastcamz_olivine_02.png` |
| `olivine_02` | 420 | Navcam (left) | 2022-04-26 | `23_2532` | 294 m | NASA/JPL-Caltech | [page](https://mars.nasa.gov/mars2020/multimedia/raw-images/NLF_0420_0704213192_121ECM_N0232532NCAM13419_01_195J) | `sol0420_navcam_olivine_02.png` |
| `carbonate_01` | 708 | Mastcam-Z (left) | 2023-02-16 | `33_612` | 157 m | NASA/JPL-Caltech/ASU | [page](https://mars.nasa.gov/mars2020/multimedia/raw-images/ZL0_0708_0729786082_784EBY_N0330612ZCAM08702_1100LMJ) | `sol0708_mastcamz_carbonate_01.png` |
| `carbonate_01` | 707 | Navcam (left) | 2023-02-15 | `33_612` | 157 m | NASA/JPL-Caltech | [page](https://mars.nasa.gov/mars2020/multimedia/raw-images/NLF_0707_0729715231_043ECM_N0330612NCAM13707_01_195J) | `sol0707_navcam_carbonate_01.png` |
| `carbonate_02` | 708 | Mastcam-Z (left) | 2023-02-16 | `33_1756` | 141 m | NASA/JPL-Caltech/ASU | [page](https://mars.nasa.gov/mars2020/multimedia/raw-images/ZL0_0708_0729803086_660EBY_N0331756ZCAM08709_1100LMJ) | `sol0708_mastcamz_carbonate_02.png` |
| `carbonate_02` | 708 | Navcam (left) | 2023-02-16 | `33_1756` | 141 m | NASA/JPL-Caltech | [page](https://mars.nasa.gov/mars2020/multimedia/raw-images/NLF_0708_0729807310_316ECM_N0331756NCAM12708_01_185J) | `sol0708_navcam_carbonate_02.png` |
| `clay_01` | 436 | Mastcam-Z (left) | 2022-05-12 | `24_3290` | 48 m | NASA/JPL-Caltech/ASU | [page](https://mars.nasa.gov/mars2020/multimedia/raw-images/ZL0_0436_0705645706_223EBY_N0243290ZCAM08453_1100LMJ) | `sol0436_mastcamz_clay_01.png` |
| `clay_01` | 435 | Navcam (left) | 2022-05-11 | `24_3290` | 48 m | NASA/JPL-Caltech | [page](https://mars.nasa.gov/mars2020/multimedia/raw-images/NLF_0435_0705550778_508ECM_N0243290NCAM12434_01_195J) | `sol0435_navcam_clay_01.png` |
| `clay_02` | 676 | Mastcam-Z (left) | 2023-01-14 | `32_774` | 134 m | NASA/JPL-Caltech/ASU | [page](https://mars.nasa.gov/mars2020/multimedia/raw-images/ZL0_0676_0726955120_348EBY_N0320774ZCAM03519_1100LMJ) | `sol0676_mastcamz_clay_02.png` |
| `clay_02` | 674 | Navcam (left) | 2023-01-12 | `32_774` | 134 m | NASA/JPL-Caltech | [page](https://mars.nasa.gov/mars2020/multimedia/raw-images/NLF_0674_0726784330_568ECM_N0320774NCAM13674_01_195J) | `sol0674_navcam_clay_02.png` |

**Limitation:** the photos are taken from the rover position nearest to the stop, 48–294 m away. The camera pointing direction was not verified, so a photo shows the terrain around that position, not necessarily the stop at the centre of the frame. The app shows the distance next to each photo.

## 4. MEDA weather (pressure only)
- **Source:** MEDA (Mars Environmental Dynamics Analyzer) bundle, PDS Atmospheres Node, collection `data_derived_env`: <https://atmos.nmsu.edu/PDS/data/PDS4/Mars2020/mars2020_meda/data_derived_env/>. Citation: J.A. Rodriguez-Manfredi et al. (2021), *The Mars Environmental Dynamics Analyzer, MEDA*, NASA Planetary Data System, DOI 10.17189/1522849.
- **Files:** derived pressure (PS) files, each with its PDS4 `.xml` label, for sols 417, 420, 435, 674 and 708. These are the sols of the stop photos. Sol 417 was used instead of 416 because the sol 416 file is much smaller (424 KB against 2–4 MB for the others), which suggests a short record.

| Sol | Stop | Median | Min–max |
|---|---|---|---|
| 417 | olivine_01 | 725.4 Pa | 698.7–735.6 Pa |
| 420 | olivine_02 | 730.7 Pa | 706.2–747.7 Pa |
| 435 | clay_01 | 760.2 Pa | 726.8–777.7 Pa |
| 674 | clay_02 | 728.8 Pa | 714.0–744.4 Pa |
| 708 | carbonate_01, carbonate_02 | 738.6 Pa | 728.8–750.4 Pa |

These values were computed by the team pipeline from the files above and are stored in `conditions.json`. Sol 417 covers only part of the day (hours 0 and 12–23).

**Wind is not shown.** In `data_derived_env`, derived wind files (`DER_WS`) exist only up to **sol 315**; from sol 316 on, each sol holds only ANCILLARY, PS, RHS and TIRS. The calibrated collection has no wind for sol 416 either. The team decided not to borrow wind from another sol, because it would be another place and time in the mission.

## 5. Reproducing this part
1. Download the waypoints file and keep end-of-drive points inside the study box.
2. Sample the team layers at each point with `sample_layers.py` (it refuses multi-band rasters such as the RGB CRISM image).
3. Query the raw-image gallery by sol range and camera, and keep frames whose `site`/`drive` match the stop's rover position.
4. Download the MEDA derived PS files and labels listed in `meda_files.csv`.

The data files themselves (`data/photos/`, `data/meda/`) are not committed to the repository; their source links are listed in `photo_table.csv` and `meda_files.csv`.

## Sources
- NASA Mars 2020 waypoints: <https://mars.nasa.gov/mmgis-maps/M20/Layers/json/M20_waypoints.json>
- NASA Mars Perseverance raw images: <https://mars.nasa.gov/mars2020/multimedia/raw-images/>
- MEDA, PDS Atmospheres Node: <https://pds-atmospheres.nmsu.edu/data_and_services/atmospheres_data/PERSEVERANCE/meda.html>
- CRISM mineral map of Jezero (Parente, Itoh, Saranathan), Zenodo 5575824
- USGS Mars 2020 TRN HiRISE DTM mosaic, <https://doi.org/10.5066/P9REJ9JN>
