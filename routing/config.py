"""Every number the route engine uses, in one place, with its source.

Two kinds of values live here:
  SOURCED     - taken from a cited NASA / peer-reviewed source.
  ASSUMPTION  - a modelling choice we made because no source gives the value
                for Mars. These are shown to users as assumptions, and every one
                can be changed here without touching the algorithms.
"""

# ---------------------------------------------------------------- reference limits
# Team decision (Nov 14): these are NOT hard bans. Routes may cross them; every
# route reports how much of it exceeds each limit so the astronaut can decide.
# The only cells nobody can enter are cells without elevation data.
# SOURCED: xEVA suit capability "walking up/down/across a slope of up to 20 deg"
# NASA Exploration EVA Integrated HITL Testing and Analogs (Coan, 2021), NTRS 20210000827.
# Lunar (Artemis) value; no official Mars value exists.
# Team decision: this is a REFERENCE, not a hard limit. Steep ground is never forbidden;
# its cost (Tobler speed + Pandolf grade term) makes the planner avoid it, and any
# route that still crosses more than this is flagged in the output.
MAX_SLOPE_DEG = 20.0
HARD_SLOPE_LIMIT = False

# SOURCED: surfaces with thermal inertia < 100 J m-2 K-1 s-1/2 may not be load-bearing
# or trafficable. Fergason et al. 2012, Space Sci Rev, doi:10.1007/s11214-012-9891-3.
MIN_THERMAL_INERTIA = 100.0

# ASSUMPTION (from our own inspection of the DTM): a rectangular strip of anomalous
# roughness at lon 77.32-77.35 E, near the western edge of the mosaic, looks like a
# different stereo model / known DTM artefact zone. Cells west of this longitude are
# not walkable. The exact boundary of the bad zone is unknown; our study area (lon
# ~77.39-77.42) is far from it, so this rule never changes our routes.
WEST_EDGE_LON = 77.35

# SOURCED: EVAs of up to 8 hours (6 +/- 2 h). Coan 2021 (above); EVA-EXP-0075.
EVA_MAX_H = 8.0
EVA_NOMINAL_H = 6.0

# SOURCED: exploration excursions of up to a 2 km radius from the lander (TBR).
# Exploration EVA System Concept of Operations Summary, EVA-EXP-0075.
OPERATING_RADIUS_M = 2000.0

# ---------------------------------------------------------------- walking speed
# SOURCED: Apollo planners assumed 3.6 km/h average for a walkback of up to one hour.
# Apollo Lunar Surface Journal (NASA), "Apollo 11 gaits".
FLAT_SPEED_KMH = 3.6

# SOURCED (form): Tobler's hiking function v = 6 exp(-3.5 |s + 0.05|) km/h, s = dz/dx.
# Used for analog-mission traverse planning (Meili-I analog study, UCL / Acta Astronautica).
# ASSUMPTION: we rescale it so flat ground gives FLAT_SPEED_KMH, keeping Tobler's shape.
TOBLER_A, TOBLER_B, TOBLER_C = 6.0, 3.5, 0.05

# ---------------------------------------------------------------- effort / metabolism
# SOURCED (form): Pandolf load-carriage equation, used by NASA for EVA traverse
# workload (NTRS 20240001423). Its speed and grade terms are 1.5 V^2 and 0.35 V G
# (V in m/s, G in % grade). We use their RATIO to scale effort with grade:
#   relative rate = 1 + (0.35 V G) / (1.5 V^2)
PANDOLF_STAND_COEF = 1.5   # standing term 1.5 W
PANDOLF_SPEED_COEF = 1.5
PANDOLF_GRADE_COEF = 0.35
# ASSUMPTION: walking downhill is never counted as cheaper than flat (conservative).
DOWNHILL_MIN_REL = 1.0

# ASSUMPTION: terrain difficulty multiplier (Pandolf's "terrain factor" idea, eta >= 1).
#   eta = 1 + ROUGH_WEIGHT * roughness_deg / ROUGH_REF_DEG
#           + SOIL_WEIGHT  * soil_softness   (0 = firm, 1 = softest in the area)
# Pandolf's published eta spans 1.0 (paved) to 2.1 (loose sand); we cap at ETA_MAX.
ROUGH_WEIGHT, ROUGH_REF_DEG = 0.5, 10.0
SOIL_WEIGHT = 0.5
ETA_MAX = 2.1
# soil softness is mapped linearly from thermal inertia between these values:
# SOURCED: THEMIS TI 205-255 interpreted as fine sand, 255-375 medium/coarse sand
# (Fergason, MSL landing site workshop). Below SOFT_TI = softest, above FIRM_TI = firm.
SOFT_TI, FIRM_TI = 205.0, 375.0

# ---------------------------------------------------------------- oxygen
# SOURCED: advanced EMU sized for 8 h at 1200 BTU/h; Apollo EMU 8 h @ 930, 6 h @ 1200,
# 5 h @ 1600 BTU/h (i.e. roughly a fixed energy budget). NASA plans future planetary
# EVAs at 1200 BTU/h average (Mars Spacesuit Mass Requirements, ICES-2026-127).
REFERENCE_RATE_BTU_H = 1200.0
# ASSUMPTION: walking on flat, smooth ground is taken as the reference rate, so
# "oxygen hours" = hours of supply at 1200 BTU/h, and each segment spends
# time_h * relative_metabolic_rate of them.

# ---------------------------------------------------------------- emergency
# ASSUMPTION (user-editable in the app): reserve kept unused in emergency planning.
EMERGENCY_MARGIN = 0.25

# ---------------------------------------------------------------- comms / shelters
# ASSUMPTION: antenna height above ground at the base, and astronaut antenna height.
BASE_ANTENNA_H_M = 3.0
SUIT_ANTENNA_H_M = 1.8
# ASSUMPTION: horizon search radius and number of azimuths for sky-view.
SKYVIEW_RADIUS_M = 500.0
SKYVIEW_AZIMUTHS = 16

# ASSUMPTION: default time spent working at each science stop (user-editable).
DEFAULT_DWELL_MIN = 30.0
