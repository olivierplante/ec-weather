"""Constants for the EC Weather integration."""

from datetime import timedelta

DOMAIN = "ec_weather"

# Config entry data keys
CONF_LANGUAGE = "language"
CONF_CITY_CODE = "city_code"
CONF_CITY_NAME = "city_name"
CONF_LAT = "lat"
CONF_LON = "lon"
CONF_BBOX = "bbox"
CONF_AQHI_LOCATION_ID = "aqhi_location_id"
CONF_GEOMET_BBOX = "geomet_bbox"

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = {"en": "English", "fr": "Français"}

# EC API
EC_API_BASE = "https://api.weather.gc.ca"

# Request timeout (seconds)
REQUEST_TIMEOUT = 15

# Retry settings for transient network/DNS failures
FETCH_RETRIES = 3
FETCH_RETRY_DELAY = 5  # seconds between retries

# ---------------------------------------------------------------------------
# Polling modes
#
# Minimal (default): Only alerts poll. Everything else refreshes on-demand
#   when the dashboard is viewed. Lowest API usage.
#
# Efficient: Alerts + current conditions + AQHI poll continuously.
#   Forecasts and WEonG refresh on-demand. Good for users with iOS widgets,
#   temperature automations, or AQHI alerts.
#
# Full: Everything polls at configured intervals. Highest API usage.
#   For power users or data loggers.
# ---------------------------------------------------------------------------
CONF_POLLING_MODE = "polling_mode"
POLLING_MODE_MINIMAL = "minimal"
POLLING_MODE_EFFICIENT = "efficient"
POLLING_MODE_FULL = "full"
DEFAULT_POLLING_MODE = POLLING_MODE_MINIMAL

POLLING_MODES = {
    POLLING_MODE_MINIMAL: "Minimal — only alerts poll, everything else on-demand",
    POLLING_MODE_EFFICIENT: "Efficient — alerts + conditions + AQHI poll, forecasts on-demand",
    POLLING_MODE_FULL: "Full — everything polls continuously",
}

# Update intervals
SCAN_INTERVAL_ALERTS = timedelta(minutes=30)  # alerts always poll in all modes

# Configurable interval defaults (minutes)
CONF_WEATHER_INTERVAL = "weather_interval"
CONF_AQHI_INTERVAL = "aqhi_interval"
CONF_WEONG_INTERVAL = "weong_interval"
DEFAULT_WEATHER_INTERVAL = 30    # minutes — EC updates conditions ~6x/hour
DEFAULT_WEONG_INTERVAL = 360     # minutes (6h) — matches HRDPS model run cycle
DEFAULT_AQHI_INTERVAL = 180      # minutes (3h) — EC publishes AQHI hourly, forecasts 2x/day

# Service names
SERVICE_FETCH_DAY_TIMESTEPS = "fetch_day_timesteps"

# WEonG concurrency
WEONG_SEMAPHORE_LIMIT = 20

# GeoMet WMS configuration (WEonG precipitation probability)
GEOMET_BASE_URL = "https://geo.weather.gc.ca/geomet"
GEOMET_CRS = "EPSG:4326"
GEOMET_REQUEST_TIMEOUT = 10  # seconds, per individual GetFeatureInfo request

# WEonG cache TTLs — model data doesn't change between runs
WEONG_CACHE_TTL_HRDPS = 6 * 3600   # seconds — HRDPS runs every 6h
WEONG_CACHE_TTL_GDPS = 12 * 3600   # seconds — GDPS runs every 12h

# Coordinator storage keys
COORDINATOR_WEATHER = "weather"
COORDINATOR_ALERTS = "alerts"
COORDINATOR_AQHI = "aqhi"
COORDINATOR_WEONG = "weong"

# AQHI risk levels — thresholds from EC's Air Quality Health Index scale
AQHI_RISK_LOW = "low"
AQHI_RISK_MODERATE = "moderate"
AQHI_RISK_HIGH = "high"
AQHI_RISK_VERY_HIGH = "very_high"


def aqhi_risk_level(aqhi: float | None) -> str | None:
    """Map an AQHI value to a risk level string.

    EC AQHI scale: 1-3 low, 4-6 moderate, 7-10 high, 11+ very high.
    """
    if aqhi is None:
        return None
    if aqhi <= 3:
        return AQHI_RISK_LOW
    if aqhi <= 6:
        return AQHI_RISK_MODERATE
    if aqhi <= 10:
        return AQHI_RISK_HIGH
    return AQHI_RISK_VERY_HIGH

# Gauge sensor temperature range (Celsius)
GAUGE_TEMP_MIN = -40.0
GAUGE_TEMP_MAX = 40.0
