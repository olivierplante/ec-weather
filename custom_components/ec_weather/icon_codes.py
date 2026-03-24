"""EC Weather icon code constants.

Environment Canada uses numeric icon codes to represent weather conditions.
Day (0-29) and night (30-48) variants exist for conditions affected by
time of day (clear, partly cloudy, etc.).

Reference: EC's icon set at weather.gc.ca
"""

# --- Precipitation icons (same day/night) ---
CLOUDY = 10
RAIN = 12
RAIN_HEAVY = 13
FREEZING_RAIN = 14
RAIN_AND_SNOW = 15
SNOW_LIGHT = 16
SNOW = 17
SNOW_HEAVY = 18
THUNDERSTORM = 19
HAIL = 26
ICE_PELLETS = 27

# --- Day icons ---
SUNNY = 0
MAINLY_SUNNY = 1
PARTLY_CLOUDY_DAY = 2
MOSTLY_CLOUDY_DAY = 3

# --- Night icons ---
CLEAR_NIGHT = 30
MAINLY_CLEAR_NIGHT = 31
PARTLY_CLOUDY_NIGHT = 32
MOSTLY_CLOUDY_NIGHT = 33
