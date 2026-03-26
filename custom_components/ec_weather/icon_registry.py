"""EC Weather icon registry — single source of truth for icon mappings.

Environment Canada uses numeric icon codes (0-48) to represent weather
conditions.  Day (0-29) and night (30-48) variants exist for conditions
affected by time of day (clear, partly cloudy, etc.).

This module consolidates:
  - Named constants for icon codes used in derive_icon / transforms
  - ICON_CONDITIONS: icon code -> HA weather condition string
  - ICON_MDI: icon code -> MDI icon string (canonical reference for JS card)
  - icon_code_to_condition(): lookup helper with cloudy fallback

Reference: EC's icon set at weather.gc.ca
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Named constants (used by transforms.py derive_icon)
# ---------------------------------------------------------------------------

# Precipitation icons (same day/night)
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

# Day icons
SUNNY = 0
MAINLY_SUNNY = 1
PARTLY_CLOUDY_DAY = 2
MOSTLY_CLOUDY_DAY = 3

# Night icons
CLEAR_NIGHT = 30
MAINLY_CLEAR_NIGHT = 31
PARTLY_CLOUDY_NIGHT = 32
MOSTLY_CLOUDY_NIGHT = 33

# ---------------------------------------------------------------------------
# Icon code -> HA weather condition string
# ---------------------------------------------------------------------------

ICON_CONDITIONS: dict[int, str] = {
    0: "sunny",
    1: "partlycloudy",
    2: "partlycloudy",
    3: "cloudy",
    4: "cloudy",
    5: "partlycloudy",
    6: "rainy",
    7: "snowy-rainy",
    8: "snowy",
    9: "lightning-rainy",
    10: "cloudy",
    11: "rainy",
    12: "rainy",
    13: "pouring",
    14: "hail",
    15: "snowy-rainy",
    16: "snowy",
    17: "snowy",
    18: "snowy",
    19: "lightning-rainy",
    20: "windy",
    21: "fog",
    22: "partlycloudy",
    23: "fog",
    24: "fog",
    25: "windy",
    26: "hail",
    27: "hail",
    28: "hail",
    29: "cloudy",
    30: "clear-night",
    31: "clear-night",
    32: "partlycloudy",
    33: "cloudy",
    34: "cloudy",
    35: "clear-night",
    36: "rainy",
    37: "snowy-rainy",
    38: "snowy",
    39: "lightning-rainy",
    40: "snowy",
    41: "exceptional",
    42: "exceptional",
    43: "windy",
    44: "fog",
    45: "windy",
    46: "lightning",
    47: "lightning",
    48: "exceptional",
}

# ---------------------------------------------------------------------------
# Icon code -> MDI icon string
# Canonical source for the JS card (ec-weather-card.js EC_ICON_MAP).
# ---------------------------------------------------------------------------

ICON_MDI: dict[int, str] = {
    0: "mdi:weather-sunny",
    1: "mdi:weather-partly-cloudy",
    2: "mdi:weather-partly-cloudy",
    3: "mdi:weather-cloudy",
    4: "mdi:weather-cloudy",
    5: "mdi:weather-partly-cloudy",
    6: "mdi:weather-rainy",
    7: "mdi:weather-snowy-rainy",
    8: "mdi:weather-snowy",
    9: "mdi:weather-lightning-rainy",
    10: "mdi:weather-cloudy",
    11: "mdi:weather-rainy",
    12: "mdi:weather-rainy",
    13: "mdi:weather-rainy",
    14: "mdi:weather-hail",
    15: "mdi:weather-snowy-rainy",
    16: "mdi:weather-snowy",
    17: "mdi:weather-snowy",
    18: "mdi:weather-snowy",
    19: "mdi:weather-lightning-rainy",
    20: "mdi:weather-windy",
    21: "mdi:weather-fog",
    22: "mdi:weather-partly-cloudy",
    23: "mdi:weather-fog",
    24: "mdi:weather-fog",
    25: "mdi:weather-windy",
    26: "mdi:weather-hail",
    27: "mdi:weather-hail",
    28: "mdi:weather-rainy",
    29: "mdi:weather-cloudy",
    30: "mdi:weather-night",
    31: "mdi:weather-night-partly-cloudy",
    32: "mdi:weather-night-partly-cloudy",
    33: "mdi:weather-cloudy",
    34: "mdi:weather-cloudy",
    35: "mdi:weather-night-partly-cloudy",
    36: "mdi:weather-rainy",
    37: "mdi:weather-snowy-rainy",
    38: "mdi:weather-snowy",
    39: "mdi:weather-lightning-rainy",
    40: "mdi:weather-snowy",
    41: "mdi:weather-tornado",
    42: "mdi:weather-tornado",
    43: "mdi:weather-windy",
    44: "mdi:weather-fog",
    45: "mdi:weather-windy",
    46: "mdi:weather-lightning",
    47: "mdi:weather-lightning",
    48: "mdi:weather-tornado",
}


# ---------------------------------------------------------------------------
# Icon code -> bilingual condition text (for WEonG-derived icons)
# ---------------------------------------------------------------------------

CONDITION_TEXT: dict[int, dict[str, str]] = {
    SUNNY: {"en": "Sunny", "fr": "Ensoleillé"},
    MAINLY_SUNNY: {"en": "Mainly sunny", "fr": "Généralement ensoleillé"},
    PARTLY_CLOUDY_DAY: {"en": "Partly cloudy", "fr": "Partiellement nuageux"},
    MOSTLY_CLOUDY_DAY: {"en": "Mostly cloudy", "fr": "Généralement nuageux"},
    CLOUDY: {"en": "Cloudy", "fr": "Nuageux"},
    RAIN: {"en": "Rain", "fr": "Pluie"},
    FREEZING_RAIN: {"en": "Freezing rain", "fr": "Pluie verglaçante"},
    RAIN_AND_SNOW: {"en": "Rain and snow", "fr": "Pluie et neige"},
    SNOW: {"en": "Snow", "fr": "Neige"},
    ICE_PELLETS: {"en": "Ice pellets", "fr": "Grésil"},
    CLEAR_NIGHT: {"en": "Clear", "fr": "Dégagé"},
    MAINLY_CLEAR_NIGHT: {"en": "Mainly clear", "fr": "Généralement dégagé"},
    PARTLY_CLOUDY_NIGHT: {"en": "Partly cloudy", "fr": "Partiellement nuageux"},
    MOSTLY_CLOUDY_NIGHT: {"en": "Mostly cloudy", "fr": "Généralement nuageux"},
}


def condition_text(code: int | None, lang: str = "en") -> str | None:
    """Return localized condition text for a WEonG-derived icon code."""
    if code is None:
        return None
    entry = CONDITION_TEXT.get(code)
    if entry:
        return entry.get(lang, entry.get("en"))
    return None


def icon_code_to_condition(code: int | None) -> str | None:
    """Map an EC icon code to an HA weather condition string."""
    if code is None:
        return None
    return ICON_CONDITIONS.get(code, "cloudy")
