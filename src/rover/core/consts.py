"""Frozen constants shared by several layers (SPEC 6.2, 3.4, 4.2, 7.1). FROZEN until J6: additions only."""

GTYPE_ROCK, GTYPE_SAND, GTYPE_DUST, GTYPE_ICE = 0, 1, 2, 3
GTYPE_NAMES = ("rock", "sand", "dust", "ice")
RAMP_BASE = {GTYPE_ROCK: 0, GTYPE_SAND: 6, GTYPE_DUST: 12, GTYPE_ICE: 12}
SKY = (18, 21)
DARK = (22, 23)
N_SENSOR_COLORS = 24

# Luminance (2R + 5G + B) // 8 of palette indices 0-23 (SPEC 7.1). Input of M2: never recomputed from the display palette.
CAM_LUT = (16, 35, 54, 75, 104, 135, 24, 65, 108, 151, 168, 186, 36, 90, 144, 199, 214, 229, 166, 147, 121, 99, 3, 18)

MODES = ("BABBLE", "DRIVE", "SEEK_SUN", "SLEEP", "SAFE", "DRILL", "ANALYZE")
MODE_LABELS = {
    "BABBLE": "MOTOR BABBLING",
    "DRIVE": "DRIVE TO TARGET",
    "SEEK_SUN": "SEEK SUN",
    "SLEEP": "SLEEP",
    "SAFE": "SAFE MODE",
    "DRILL": "DRILL",
    "ANALYZE": "ANALYZE",
}

# M0 input vector (24 values, SPEC 3.4): 0-1 enc_L enc_R; 2-3 pitch roll; 4 slip; 5-6 prev u; 7-14 visual features f0..f7;
# 15-17 target (cos, sin, dist); 18-21 battery, elev, cos(hour), sin(hour); 22-23 reserved P2.
_S0 = (0, 1, 4, 5, 6)
_S2 = (0, 1, 2, 3, 4, 5, 6) + tuple(range(7, 15)) + (15, 16, 17)
_S3 = _S2 + (18, 19, 20, 21)
_S4 = _S3 + (22, 23)
M0_ACTIVE = (_S0, _S0, _S2, _S3, _S4, _S4)
M0_N_IN = 24
