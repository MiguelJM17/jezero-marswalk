# Curated field data

Source tables the pipeline reads. They were compiled by hand by Ronald Aguirre from NASA sources and
checked against the rover record. **Their column names and some values are in Spanish**,
because that is how they were authored; the code reads them by those names, so they are
kept as they are rather than renamed. This file is the key.

| File | What it is | Used by |
|---|---|---|
| `proposed_stops.csv` | The candidate science stops: mineral class, coordinates, patch size, distance to the habitat, and which rover photos are nearest | `routing/export_handoff.py --stops` |
| `photo_table.csv` | One row per Perseverance photo used in the app: sol, camera, date, credit, source links, and how far the rover was from the stop | `routing/export_handoff.py --photos` |
| `rover_waypoints_minerals.csv` | Perseverance's end-of-drive positions with the mineral classification of each point | `routing/export_handoff.py --rover` |
| `meda_files.csv` | Index of the MEDA pressure files downloaded from the PDS Atmospheres Node | `processing/meda_summary.py` (reference) |
| `sample_layers.py` | Small script to sample the grid layers at given points | manual checks |

## Spanish column names

| Column | Meaning |
|---|---|
| `opcion` | stop option set (A or B) |
| `grupo` | mineral group |
| `mineral_clase` | mineral class code from the CRISM map |
| `celdas_alta_conf_3x3` | high-confidence cells in a 3x3 window |
| `tamano_parche_celdas` | mineral patch size, in grid cells |
| `dist_al_habitat_m` | straight-line distance to the habitat, in metres |
| `foto_sol_desde` / `foto_sol_hasta` | sol range of the nearest photos |
| `dist_foto_a_parada_m` | distance from the rover's camera position to the stop, in metres |
| `lugar` | stop name |
| `camara` | camera (`izquierda` = left, `derecha` = right) |
| `fecha_utc` | date, UTC |
| `credito` | image credit |
| `enlace_foto` / `enlace_descarga` | page link / direct download link |
| `archivo` | local file name |
| `tamano` | file size |

Mineral names also appear in Spanish inside some values (`olivino` = olivine,
`arcilla` = clay, `carbonato` = carbonate). The English name is always present alongside it.
