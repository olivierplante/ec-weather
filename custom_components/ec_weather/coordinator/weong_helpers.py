"""Pure helper functions and constants for WEonG aggregation."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from ..timestep_store import TimestepData


# ---------------------------------------------------------------------------
# WEonG layer definitions per model family
# ---------------------------------------------------------------------------

_HRDPS_PREFIX = "HRDPS-WEonG_2.5km_"
_GDPS_PREFIX = "GDPS-WEonG_15km_"

_LAYER_SUFFIXES: dict[str, str] = {
    "precip_prob": "Precip-Prob",
    "snow_amt": "SolidSnowCondAmt",
    "rain_amt": "LiquidPrecipCondAmt",
    "freezing_precip_amt": "FreezingPrecipCondAmt",
    "ice_pellet_amt": "IcePelletsCondAmt",
    "air_temp": "AirTemp",
    "sky_state": "SkyState",
}

# Temperature thresholds to reduce API calls by skipping impossible precip types.
# Snow is physically impossible above ~2 deg C, rain below ~-2 deg C.
# We use +/-3 deg C as a safe buffer around the transition zone.
_WARM_THRESHOLD = 3.0   # deg C -- above this, only query rain layers
_COLD_THRESHOLD = -3.0  # deg C -- below this, only query snow/ice layers

# Which amount layers to query per temperature regime
_AMT_LAYERS_WARM = ("rain_amt",)
_AMT_LAYERS_COLD = ("snow_amt", "freezing_precip_amt", "ice_pellet_amt")
_AMT_LAYERS_TRANSITION = ("rain_amt", "snow_amt", "freezing_precip_amt", "ice_pellet_amt")

# Folding: freezing precip -> rain, ice pellets -> snow
_FOLD_TO_RAIN = ("rain_amt", "freezing_precip_amt")
_FOLD_TO_SNOW = ("snow_amt", "ice_pellet_amt")

# Unit conversions: raw GeoMet value -> mm (for rain-like) or cm (for snow-like).
# Most layers return meters, but FreezingPrecipCondAmt returns mm directly.
# rain_amt: m -> mm (x1000), freezing_precip_amt: mm -> mm (x1),
# snow_amt: m -> cm (x100), ice_pellet_amt: m -> cm (x100).
_TO_MM: dict[str, int] = {"rain_amt": 1000, "freezing_precip_amt": 1}
_TO_CM: dict[str, int] = {"snow_amt": 100, "ice_pellet_amt": 100}


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------

def _weong_layer_name(suffix: str, model: str) -> str:
    """Build the full WMS layer name for the given model ('hrdps' or 'gdps')."""
    if model == "hrdps":
        return f"{_HRDPS_PREFIX}{suffix}"
    return f"{_GDPS_PREFIX}{suffix}.3h"


def _models_for_day(days_ahead: int) -> list[tuple[str, int]]:
    """Return list of (model, step_hours) to query for a given day offset.

    Days 0-1: HRDPS only (1h steps, reliable ~48h coverage).
    Day 2: Both HRDPS (1h, may partially cover) and GDPS (3h, full coverage).
           HRDPS data is preferred; GDPS fills gaps.
    Days 3+: GDPS only (3h steps).
    """
    if days_ahead <= 1:
        return [("hrdps", 1)]
    if days_ahead == 2:
        return [("hrdps", 1), ("gdps", 3)]
    return [("gdps", 3)]


def _bare_layer_name(layer: str) -> str:
    """Strip HRDPS/GDPS prefix and optional '.3h' suffix from a layer name.

    Returns the bare suffix portion, e.g. 'Precip-Prob' from
    'HRDPS-WEonG_2.5km_Precip-Prob' or 'GDPS-WEonG_15km_Precip-Prob.3h'.
    """
    bare = layer
    for prefix in (_HRDPS_PREFIX, _GDPS_PREFIX):
        if bare.startswith(prefix):
            bare = bare[len(prefix):]
            break
    return bare.removesuffix(".3h")


def _model_from_layer(layer: str) -> str:
    """Determine the model family from a full layer name.

    Returns 'hrdps' if the layer starts with the HRDPS prefix,
    otherwise 'gdps'.
    """
    if layer.startswith(_HRDPS_PREFIX):
        return "hrdps"
    return "gdps"


def build_periods(
    today: date,
    now_utc: datetime,
    local_tz: timezone | object,
) -> list[tuple[str, str, datetime, datetime]]:
    """Build a list of (date_str, 'day'|'night', utc_start, utc_end) tuples.

    Generates up to 6 days of day/night periods starting from the current
    time window. Past periods (whose end time is before now) are skipped.

    Day/night boundaries use local time (06:00/18:00) converted to UTC,
    matching EC's forecast period definitions and handling DST transitions.
    """
    periods: list[tuple[str, str, datetime, datetime]] = []

    for day_offset in range(7):
        current_day = today + timedelta(days=day_offset)
        date_str = current_day.isoformat()
        next_day = current_day + timedelta(days=1)

        # Day period: 06:00-18:00 local time, converted to UTC
        day_start = datetime(
            current_day.year, current_day.month, current_day.day, 6, 0, tzinfo=local_tz,
        ).astimezone(timezone.utc)
        day_end = datetime(
            current_day.year, current_day.month, current_day.day, 18, 0, tzinfo=local_tz,
        ).astimezone(timezone.utc)

        # Night period: 18:00 local - 06:00 local next day, converted to UTC
        night_start = datetime(
            current_day.year, current_day.month, current_day.day, 18, 0, tzinfo=local_tz,
        ).astimezone(timezone.utc)
        night_end = datetime(
            next_day.year, next_day.month, next_day.day, 6, 0, tzinfo=local_tz,
        ).astimezone(timezone.utc)

        # Skip periods entirely in the past
        if day_end > now_utc:
            periods.append((date_str, "day", day_start, day_end))
        if night_end > now_utc:
            periods.append((date_str, "night", night_start, night_end))

    # Limit to ~12 periods (matching typical daily forecast length)
    return periods[:12]


def build_timestep_data(
    ts_iso: str,
    model: str,
    values: dict[str, float],
) -> TimestepData:
    """Convert raw layer values into a TimestepData with unit conversion and precip folding.

    Takes the grouped values dict (suffix_key -> raw value) and returns a
    TimestepData. The caller handles grouping and store merging.
    """
    rain_mm = None
    snow_cm = None
    freezing_precip_mm = None
    ice_pellet_cm = None

    for fold_key in _FOLD_TO_RAIN:
        raw = values.get(fold_key)
        if raw is not None:
            converted = raw * _TO_MM[fold_key]
            rain_mm = max(rain_mm or 0, converted)
            if fold_key == "freezing_precip_amt":
                freezing_precip_mm = converted

    for fold_key in _FOLD_TO_SNOW:
        raw = values.get(fold_key)
        if raw is not None:
            converted = raw * _TO_CM[fold_key]
            snow_cm = max(snow_cm or 0, converted)
            if fold_key == "ice_pellet_amt":
                ice_pellet_cm = converted

    pop_raw = values.get("precip_prob")
    temp_raw = values.get("air_temp")
    sky_raw = values.get("sky_state")

    return TimestepData(
        time=ts_iso,
        temp=round(temp_raw, 1) if temp_raw is not None else None,
        pop=int(round(pop_raw)) if pop_raw is not None else None,
        rain_mm=round(rain_mm, 1) if rain_mm is not None else None,
        snow_cm=round(snow_cm, 1) if snow_cm is not None else None,
        freezing_precip_mm=round(freezing_precip_mm, 1) if freezing_precip_mm is not None else None,
        ice_pellet_cm=round(ice_pellet_cm, 1) if ice_pellet_cm is not None else None,
        sky_state=round(sky_raw, 1) if sky_raw is not None else None,
        model=model,
    )
