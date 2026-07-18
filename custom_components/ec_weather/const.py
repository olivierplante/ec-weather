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

# Yesterday's precipitation (issue #9) — EC climate-daily station.
# CONF_PRECIP_STATION_ID is the chosen CLIMATE_IDENTIFIER (or None = feature off).
# CONF_PRECIP_STATION_TYPE is "split" (reports TOTAL_RAIN/TOTAL_SNOW) or "combined".
# CONF_PRECIP_DISCOVERED flags that one-time discovery already ran for this entry,
# so we don't re-probe the API on every restart for unconfigured users.
CONF_PRECIP_STATION_ID = "precip_station_id"
CONF_PRECIP_STATION_TYPE = "precip_station_type"
CONF_PRECIP_STATION_NAME = "precip_station_name"
CONF_PRECIP_STATION_DISTANCE_KM = "precip_station_distance_km"
CONF_PRECIP_DISCOVERED = "precip_discovered"

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = {"en": "English", "fr": "Français"}

# ---------------------------------------------------------------------------
# AI alert grouping (opt-in)
#
# EC often publishes several alerts for one weather event (e.g. a severe
# thunderstorm warning plus a watch). This opt-in layer asks an LLM, via HA's
# native ai_task.generate_data service, which alerts describe the same event so
# the card can group them. It only ANNOTATES alerts — nothing is ever dropped,
# and every failure path leaves the alerts exactly as they are today.
# ---------------------------------------------------------------------------
CONF_AI_GROUPING = "ai_grouping"
CONF_AI_TASK_ENTITY = "ai_task_entity"
CONF_AI_GROUPING_INSTRUCTIONS = "ai_grouping_instructions"

DEFAULT_AI_GROUPING = False

# Hard ceiling on the LLM call — the coordinator must never block on it.
AI_GROUPING_TIMEOUT = 60  # seconds

# User-editable judgment half of the grouping prompt (the mechanical half —
# the numbered alert list and the output format — is fixed in code). This text
# is phenomenon-grounded (group only same-phenomenon alerts, with one explicit
# negative example) and scored 100/100 runs against the target small local
# model, versus systematic ordering/refusal failures from the prior default.
#
# The severity-order paragraph MUST stay LAST: small models obey the most
# recent instruction, and moving this rule mid-prompt measurably regressed the
# primary ordering.
DEFAULT_AI_GROUPING_INSTRUCTIONS = (
    "You are grouping the active weather alerts for one location so that alerts "
    "describing the same weather event are shown together.\n\n"
    "Two alerts describe the same event only when they are about the same "
    "weather phenomenon (for example thunderstorms, rain, snow, freezing rain, "
    "wind, heat, or air quality). A warning and a watch for that same "
    "phenomenon are the same event, so group them together. Alerts about "
    "different phenomena are never the same event, even when one alert's text "
    "mentions the other: a heat warning and an air quality warning are two "
    "separate events and must stay apart.\n\n"
    "The alerts may be written in English or French.\n\n"
    "When you group alerts, put the most severe one first: a warning outranks a "
    "watch, a watch outranks an advisory, an advisory outranks a statement."
)

# Superseded default prompts, kept verbatim. A stored options value that equals
# any entry here is auto-upgraded to the current DEFAULT at read time (see
# resolve_ai_grouping_instructions), so users who never customized the prompt
# track improvements without re-editing their config. Never rewrite the stored
# value itself — resolution happens only when the value is consumed.
LEGACY_AI_GROUPING_INSTRUCTIONS = (
    (
        "You are grouping active weather alerts for a single location. Group "
        "together the alerts that describe the same underlying weather event — for "
        "example one storm that has both a warning and a watch, or a rain event "
        "covered by several bulletins. Within each group, list first the alert "
        "that best describes the event or carries the highest gravity, using this "
        "order of gravity: a warning outranks a watch, a watch outranks an "
        "advisory, and an advisory outranks a statement. Only group alerts you are "
        "confident describe the same event; when in doubt, leave an alert on its "
        "own rather than grouping it. The alerts may be written in English or "
        "French."
    ),
)


def resolve_ai_grouping_instructions(stored: str | None) -> str:
    """Return the effective grouping instructions for a stored options value.

    A missing/blank value, or one that exactly matches a superseded default in
    ``LEGACY_AI_GROUPING_INSTRUCTIONS``, resolves to the current
    ``DEFAULT_AI_GROUPING_INSTRUCTIONS`` so uncustomized users automatically
    track prompt improvements. Any other (customized) value is returned
    unchanged — customized prompts always win. Read-time only: the stored
    option is never mutated here.
    """
    if stored is None or not stored.strip():
        return DEFAULT_AI_GROUPING_INSTRUCTIONS
    if stored in LEGACY_AI_GROUPING_INSTRUCTIONS:
        return DEFAULT_AI_GROUPING_INSTRUCTIONS
    return stored

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
# Yesterday's precip: retry every 30 min until yesterday's data publishes
# (typically by ~06:00 local), then stay idle until the next day.
SCAN_INTERVAL_CLIMATE = timedelta(minutes=30)

# Extended-forecast scope (options flow). Gates how far the daily forecast
# reaches: 7 = official EC days only (default), 10/14 = plus GEPS model outlook
# rows for the calendar days beyond EC's 7-day list. Stored as a string by the
# select selector; consumers coerce with int().
CONF_FORECAST_DAYS = "forecast_days"
DEFAULT_FORECAST_DAYS = 7
# Legacy select key kept readable for entries saved by the pre-checkbox flow.
CONF_EXTENDED_FORECAST = "extended_forecast"
EXTENDED_FORECAST_DAYS = 14

# ---------------------------------------------------------------------------
# Model-derived daily precipitation estimate (opt-in, BETA)
#
# The daily forecast normally shows only EC-stated accumulation amounts. When
# this option is on, days where EC states no amount fall back to an honest
# probability-weighted model expectation (see timestep_store.project_periods).
# Off by default — the model estimate is a beta refinement, not the baseline.
# ---------------------------------------------------------------------------
CONF_MODEL_PRECIP_ESTIMATE = "model_precip_estimate"
DEFAULT_MODEL_PRECIP_ESTIMATE = False

# Configurable interval defaults (minutes)
CONF_WEATHER_INTERVAL = "weather_interval"
CONF_AQHI_INTERVAL = "aqhi_interval"
DEFAULT_WEATHER_INTERVAL = 30    # minutes — EC updates conditions ~6x/hour
DEFAULT_AQHI_INTERVAL = 180      # minutes (3h) — EC publishes AQHI hourly, forecasts 2x/day

# Service names
SERVICE_FETCH_DAY_TIMESTEPS = "fetch_day_timesteps"

# WEonG concurrency
WEONG_SEMAPHORE_LIMIT = 20

# ---------------------------------------------------------------------------
# WEonG degraded-API resilience
#
# EC's GeoMet API degrades sometimes (timeouts, HTTP 429, high latency). These
# constants keep a degradation episode from caching failure holes with the
# normal TTL and from spiking a cold-start burst into a struggling server.
# ---------------------------------------------------------------------------
# A day's timeline is only marked complete (cached, no retry) when at least this
# fraction of its base POP+AirTemp queries returned a value. Below it the day
# stays "pending" so the existing 15-minute retry refetches it instead of
# caching the holes and serving them until the next model run.
WEONG_DAY_COMPLETE_MIN_RATIO = 0.6
# Cold-start pacing: the wave runs its GeoMet queries in semaphore-sized chunks
# with this delay (seconds) between chunks, so a reboot does not spike hundreds
# of near-concurrent requests into a possibly-degraded server.
WEONG_CHUNK_DELAY_SECONDS = 0.3
# HTTP 429 two-step backoff (seconds): the first 429 in a wave pauses the short
# amount, a second or later 429 pauses the longer amount. No retry framework —
# just a brief breather so the wave stops hammering a rate-limiting server.
WEONG_BACKOFF_FIRST_SECONDS = 3
WEONG_BACKOFF_SECOND_SECONDS = 8

# GeoMet WMS configuration (WEonG precipitation probability)
GEOMET_BASE_URL = "https://geo.weather.gc.ca/geomet"
GEOMET_CRS = "EPSG:4326"
GEOMET_REQUEST_TIMEOUT = 10  # seconds, per individual GetFeatureInfo request

# WEonG cache TTLs — model data doesn't change between runs
WEONG_CACHE_TTL_HRDPS = 6 * 3600   # seconds — HRDPS runs every 6h
WEONG_CACHE_TTL_RDPS = 6 * 3600    # seconds — RDPS runs every 6h (00/06/12/18Z)
# GEPS ensemble (extended forecast, days 4+) runs twice a day at 00Z/12Z, so a
# 12h TTL keeps the extended wave to one fetch per model run.
CACHE_TTL_GEPS = 12 * 3600         # seconds — GEPS runs every 12h (00/12Z)

# Persistent forecast cache (reboots restore state instead of refetching).
# STORAGE_VERSION is the HA Store file version; STORAGE_SCHEMA_VERSION guards
# the payload shape (a mismatch discards the file and refetches, never
# migrate-by-guess). STORAGE_SAVE_DELAY debounces writes after a wave.
STORAGE_VERSION = 1
STORAGE_SCHEMA_VERSION = 1
STORAGE_SAVE_DELAY = 5  # seconds — async_delay_save debounce window

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
