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

# Update intervals
SCAN_INTERVAL_WEATHER = timedelta(minutes=30)
SCAN_INTERVAL_ALERTS = timedelta(minutes=30)
SCAN_INTERVAL_AQHI = timedelta(hours=3)  # EC publishes AQHI forecasts ~2x/day
SCAN_INTERVAL_WEONG = timedelta(minutes=60)

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

# AQHI risk levels
AQHI_RISK = {
    range(1, 4): "low",
    range(4, 7): "moderate",
    range(7, 11): "high",
}
AQHI_RISK_VERY_HIGH = "very_high"
AQHI_RISK_LOW = "low"

# Gauge sensor temperature range (Celsius)
GAUGE_TEMP_MIN = -40.0
GAUGE_TEMP_MAX = 40.0
