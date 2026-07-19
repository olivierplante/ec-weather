"""Pure helper functions and constants for the GEPS extended forecast.

Phase A of the extended-forecast plan (specs/ec_weather/weong-far-days-plan.md):
the pure, table-driven-testable synthesis layer. GEPS is the single extended
source — p50 for continuous fields, probability shape for precip. Everything
here is pure: no I/O, no hass, no network. The coordinator phase wires these
into fetching and validates the layer strings / window convention live.

Icon codes reuse the existing EC vocabulary in ``icon_registry`` (the same
codes WEonG SkyState derivation produces). Nothing here invents a new code:
  - clear/partly/mostly/cloudy come from the cloud buckets used by
    ``transforms.derive_icon`` (SUNNY, PARTLY_CLOUDY_*, MOSTLY_CLOUDY_*, CLOUDY);
  - rain/snow precip icons are RAIN / SNOW;
  - the "chance of" family reuses EC codes 6 (chance of showers -> rainy) and
    8 (chance of flurries -> snowy), both already present in
    ``icon_registry.ICON_CONDITIONS`` / ``ICON_MDI``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..icon_registry import (
    CHANCE_OF_FLURRIES,
    CHANCE_OF_SHOWERS,
    CLEAR_NIGHT,
    CLOUDY,
    FREEZING_RAIN,
    HAIL,
    ICE_PELLETS,
    MAINLY_CLEAR_NIGHT,
    MAINLY_SUNNY,
    MOSTLY_CLOUDY_DAY,
    MOSTLY_CLOUDY_NIGHT,
    PARTLY_CLOUDY_DAY,
    PARTLY_CLOUDY_NIGHT,
    RAIN,
    RAIN_AND_SNOW,
    RAIN_HEAVY,
    SNOW,
    SNOW_HEAVY,
    SNOW_LIGHT,
    SUNNY,
    THUNDERSTORM,
)
from ..timestamp_utils import hour_from_iso
from ..timestep_store import TimestepData
from ..transforms import display_pop


# ---------------------------------------------------------------------------
# A1 — GEPS layer names (verified live 2026-07-07/08 from one 12Z run)
# ---------------------------------------------------------------------------

# GEPS diagnostic layers are named GEPS.DIAG.{interval}_{variable}.{statistic}
# where interval is the accumulation/valid window in hours (3 for continuous
# fields, 12 for precip aggregates), variable is the element, and statistic is
# an ERC{percentile} (exceedance-rank percentile) or ERGE{threshold}
# (probability of >= threshold) token.
# Intervals verified live 2026-07-07 against GetCapabilities: only GUST, HMX,
# NT, TT, UVMX, WCF, WSPD publish a 3h variant. RNMM/SNMM/PRMM are precip
# accumulations and exist at 12h (and coarser) only — the 3h RNMM/SNMM layers
# phase A assumed return InvalidLayersParameter. Precip type is therefore a
# per-12h-window median, which is fine: it only feeds the wet/dry icon typing.
_GEPS_INTERVAL: dict[str, int] = {
    "TT": 3,     # temperature (3h continuous field)
    "HMX": 3,    # humidex (3h continuous field)
    "NT": 3,     # total cloud cover, percent (3h continuous field)
    "RNMM": 12,  # rain amount (12h accumulation — no 3h variant exists)
    "SNMM": 12,  # snow amount (12h accumulation — no 3h variant exists)
    "PRMM": 12,  # total precip (12h aggregates: POP + amount bands)
}


def _geps_layer(variable: str, statistic: str) -> str:
    """Build a GEPS diagnostic layer name.

    ``variable`` is the element key (TT, HMX, NT, PRMM, RNMM, SNMM) and
    ``statistic`` is the full percentile/threshold token (e.g. "ERC50",
    "ERC25", "ERGE1"). The interval prefix (3h vs 12h) is chosen per variable.
    """
    interval = _GEPS_INTERVAL[variable]
    return f"GEPS.DIAG.{interval}_{variable}.{statistic}"


# Continuous fields (3h): medians drive display, p25/p75 the outlook band.
GEPS_TEMPERATURE_P25 = _geps_layer("TT", "ERC25")
GEPS_TEMPERATURE_P50 = _geps_layer("TT", "ERC50")
GEPS_TEMPERATURE_P75 = _geps_layer("TT", "ERC75")
GEPS_HUMIDEX_P50 = _geps_layer("HMX", "ERC50")
GEPS_CLOUD_P50 = _geps_layer("NT", "ERC50")
GEPS_RAIN_MEDIAN = _geps_layer("RNMM", "ERC50")
GEPS_SNOW_MEDIAN = _geps_layer("SNMM", "ERC50")

# Precip aggregates (12h): POP is the probability of >= 1 mm; amount band is
# the p25-p75 spread (never the p50 — drizzle-biased to zero below 50% POP).
GEPS_POP_12H = _geps_layer("PRMM", "ERGE1")
GEPS_AMOUNT_P25 = _geps_layer("PRMM", "ERC25")
GEPS_AMOUNT_P75 = _geps_layer("PRMM", "ERC75")


# ---------------------------------------------------------------------------
# A2 — GEPS 12h window mapping
# ---------------------------------------------------------------------------

def geps_window_for(timestep_utc: datetime) -> tuple[datetime, datetime]:
    """Return the (start, end) of the GEPS 12h window covering ``timestep_utc``.

    GEPS 12h windows are UTC-anchored and end at 00Z and 12Z. By convention a
    value labelled AT 12:00Z covers 00Z -> 12Z, and a value AT 00:00Z covers
    the preceding 12:00Z -> 00:00Z. So a timestamp exactly on a 00Z/12Z
    boundary belongs to the window ending at that boundary; any other timestamp
    belongs to the window ending at the next boundary.

    This convention is THE tested assumption; the coordinator phase validates
    it against live GEPS metadata.
    """
    base = timestep_utc.replace(minute=0, second=0, microsecond=0)
    on_boundary = timestep_utc == base and timestep_utc.hour in (0, 12)

    if on_boundary:
        end = timestep_utc
    elif timestep_utc.hour < 12:
        end = base.replace(hour=12)
    else:
        end = (base + timedelta(days=1)).replace(hour=0)

    start = end - timedelta(hours=12)
    return start, end


def _period_bounds_utc(
    period_date: str,
    period_type: str,
    local_tz: ZoneInfo,
) -> tuple[datetime, datetime]:
    """Return the UTC (start, end) of a local day/night half.

    Mirrors ``weong_helpers.build_periods``: day is 06:00-18:00 local, night is
    18:00 local -> 06:00 local the next day. Converting local wall times to UTC
    handles DST transitions (a fall-back night is 13 hours long, spring-forward
    11 hours).
    """
    year, month, day = (int(part) for part in period_date.split("-"))
    day_date = datetime(year, month, day, tzinfo=local_tz).date()

    if period_type == "day":
        start_local = datetime(year, month, day, 6, 0, tzinfo=local_tz)
        end_local = datetime(year, month, day, 18, 0, tzinfo=local_tz)
    else:
        start_local = datetime(year, month, day, 18, 0, tzinfo=local_tz)
        next_day = day_date + timedelta(days=1)
        end_local = datetime(
            next_day.year, next_day.month, next_day.day, 6, 0, tzinfo=local_tz,
        )

    return (
        start_local.astimezone(timezone.utc),
        end_local.astimezone(timezone.utc),
    )


def window_covers_period(
    window_start_utc: datetime,
    window_end_utc: datetime,
    period_date: str,
    period_type: str,
    local_tz: ZoneInfo,
) -> bool:
    """Return True when a GEPS 12h window covers a local day/night half.

    "Covers" means the local period's midpoint falls inside the window
    ``[window_start, window_end)``. Midpoint containment gives each half exactly
    one covering window regardless of the timezone offset, so the coordinator
    can assign each 12h window to the day or night half deterministically. The
    period bounds are computed through the local timezone, so DST transitions
    shift the midpoint correctly.
    """
    period_start, period_end = _period_bounds_utc(
        period_date, period_type, local_tz,
    )
    midpoint = period_start + (period_end - period_start) / 2
    return window_start_utc <= midpoint < window_end_utc


# ---------------------------------------------------------------------------
# Shared thresholds (the ensemble icon recipe + display rules)
# ---------------------------------------------------------------------------

# Ensemble icon recipe POP tiers (percent).
_POP_PRECIP_ICON = 60   # >= this -> a solid precip icon (rain/snow)
_POP_CHANCE_ICON = 30   # >= this (but < precip) -> a "chance of" icon

# "Chance of" EC icon codes, imported from icon_registry's shared vocabulary
# (6 -> rainy / chance of showers, 8 -> snowy / chance of flurries).
_CHANCE_OF_SHOWERS = CHANCE_OF_SHOWERS
_CHANCE_OF_FLURRIES = CHANCE_OF_FLURRIES

# GEPS NT (total cloud cover, percent) buckets for the dry sky icon.
_CLOUD_CLEAR_MAX = 25    # < this -> clear / sunny
_CLOUD_PARTLY_MAX = 60   # < this -> partly cloudy
_CLOUD_MOSTLY_MAX = 85   # < this -> mostly cloudy; >= -> overcast

# EC humidex display convention (matches parsing.compute_humidex).
_HUMIDEX_MIN_TEMP = 20.0

# Outlook display / gating rules.
_POP_DISPLAY_MIN = 30    # extended rows hide POP below this
_POP_AMOUNT_MIN = 50     # amount band meaningful only at/above this POP


def _precip_is_snow(
    rain_med_mm: float | None,
    snow_med_mm: float | None,
    temp: float | None,
) -> bool:
    """Decide whether precip is snow, given rain/snow medians and temperature.

    The larger median wins; ties (including both absent or both zero) break on
    temperature at 0 degC (below freezing -> snow). Missing temperature defaults
    to rain, the more common regime.
    """
    rain = rain_med_mm if rain_med_mm is not None else 0.0
    snow = snow_med_mm if snow_med_mm is not None else 0.0
    if snow > rain:
        return True
    if rain > snow:
        return False
    # Tie -> temperature regime.
    return temp is not None and temp < 0


def _cloud_bucket_icon(cloud_pct: float | None, is_night: bool) -> int | None:
    """Map GEPS NT cloud cover (percent) onto the sky icon vocabulary.

    Uses the same day/night icon codes WEonG SkyState derivation produces.
    Returns None when cloud cover is unavailable (no icon can be honestly set).
    """
    if cloud_pct is None:
        return None
    if cloud_pct < _CLOUD_CLEAR_MAX:
        return CLEAR_NIGHT if is_night else SUNNY
    if cloud_pct < _CLOUD_PARTLY_MAX:
        return PARTLY_CLOUDY_NIGHT if is_night else PARTLY_CLOUDY_DAY
    if cloud_pct < _CLOUD_MOSTLY_MAX:
        return MOSTLY_CLOUDY_NIGHT if is_night else MOSTLY_CLOUDY_DAY
    return CLOUDY


def _ensemble_icon(
    pop: float | None,
    rain_med_mm: float | None,
    snow_med_mm: float | None,
    cloud_pct: float | None,
    is_night: bool,
    temp: float | None,
) -> int | None:
    """The ensemble icon recipe shared by timesteps and outlook halves.

    - POP >= 60 -> a solid precip icon typed by rain vs snow medians.
    - 30 <= POP < 60 -> the EC "chance of" family, typed the same way.
    - POP < 30 or POP missing -> the GEPS NT cloud bucket.
    """
    if pop is not None and pop >= _POP_PRECIP_ICON:
        return SNOW if _precip_is_snow(rain_med_mm, snow_med_mm, temp) else RAIN
    if pop is not None and pop >= _POP_CHANCE_ICON:
        if _precip_is_snow(rain_med_mm, snow_med_mm, temp):
            return _CHANCE_OF_FLURRIES
        return _CHANCE_OF_SHOWERS
    return _cloud_bucket_icon(cloud_pct, is_night)


def _humidex_feels_like(
    temp: float | None,
    humidex: float | None,
) -> float | None:
    """Gate a GEPS HMX median by EC's humidex display convention.

    Returns the humidex only when temperature is >= 20 degC and the humidex is
    at least 1 degree above it (matches parsing.compute_humidex); otherwise
    None. HMX is precomputed by GEPS, so no formula is applied here.
    """
    if temp is None or humidex is None:
        return None
    if temp < _HUMIDEX_MIN_TEMP:
        return None
    if humidex < temp + 1:
        return None
    return round(humidex, 1)


# ---------------------------------------------------------------------------
# A3 — synthesize_timestep
# ---------------------------------------------------------------------------

def synthesize_timestep(
    timestep_iso: str,
    tt_p50: float | None,
    hmx_p50: float | None,
    nt_p50: float | None,
    pop_12h: float | None,
    rain_med_mm: float | None,
    snow_med_mm: float | None,
) -> TimestepData:
    """Build a TimestepData for one GEPS 3h step (extended days 4-7).

    All inputs are GEPS ensemble statistics. The icon uses the ensemble recipe;
    feels-like is the humidex median gated by EC's convention; POP is the
    covering 12h window value (stepwise by design). Per-timestep precip amounts
    are intentionally absent — window-spanning band elements render separately.
    Missing inputs degrade gracefully: everything-None yields an empty-compatible
    timestep (temp / icon_code / pop all None).
    """
    hour = hour_from_iso(timestep_iso)
    is_night = hour < 6 or hour >= 18

    icon_code = _ensemble_icon(
        pop_12h, rain_med_mm, snow_med_mm, nt_p50, is_night, tt_p50,
    )

    return TimestepData(
        time=timestep_iso,
        temp=round(tt_p50, 1) if tt_p50 is not None else None,
        feels_like=_humidex_feels_like(tt_p50, hmx_p50),
        icon_code=icon_code,
        pop=int(round(pop_12h)) if pop_12h is not None else None,
        rain_mm=None,  # window-spanning amounts render separately
        snow_cm=None,
        model="geps",
    )


# ---------------------------------------------------------------------------
# A4 — outlook_day (day 8+ daily row + popup box payload)
# ---------------------------------------------------------------------------

def _pop_display(pop: float | None) -> int | None:
    """Resolve the outlook LIST's displayed POP.

    The extended rows keep their stricter >= 30 hide gate (on the RAW value), but
    the number they show is stepped by the shared ``display_pop`` rule (round up
    to the next 5) so every surface reads the same stepped POP. A raw POP that
    clears 30 is always >= 10, so the shared floor never hides an outlook row the
    >= 30 gate already admitted.
    """
    if pop is None or pop < _POP_DISPLAY_MIN:
        return None
    return display_pop(pop)


def outlook_day(
    date_str: str,
    tt_low_p25: float | None,
    tt_low_p50: float | None,
    tt_high_p50: float | None,
    tt_high_p75: float | None,
    pop_day: float | None,
    pop_night: float | None,
    amt_p25: float | None,
    amt_p75: float | None,
    nt_day_p50: float | None,
    nt_night_p50: float | None,
    rain_med: float | None,
    snow_med: float | None,
    hmx_day_p50: float | None,
    hmx_night_p50: float | None,
) -> dict:
    """Build the day-8+ outlook payload (daily row + slimmed popup boxes).

    Row numbers are MEDIANS (p50 low / p50 high), rendered like official rows.
    ``temp_range`` carries the p25-low to p75-high band for the popup sentence.
    Raw per-half POP is always kept; ``pop_*_display`` applies the >= 30 hide
    rule. Icons come from the ensemble recipe per half. The amount band is only
    meaningful when the wettest half reaches 50% POP.

    Honesty guard: this dict must NOT carry scalar fields the outlook cannot
    honestly fill (humidity, wind, condition text, or a per-half text summary).
    """
    wet_pop = max(
        (pop for pop in (pop_day, pop_night) if pop is not None),
        default=None,
    )
    amount_band = None
    if wet_pop is not None and wet_pop >= _POP_AMOUNT_MIN:
        amount_band = {"low": amt_p25, "high": amt_p75}

    return {
        "date": date_str,
        "source": "outlook",
        # Median scalars (rendered like official rows).
        "temp_low": tt_low_p50,
        "temp_high": tt_high_p50,
        # p25-low .. p75-high band for the popup sentence.
        "temp_range": {"low": tt_low_p25, "high": tt_high_p75},
        # Raw POP always kept; display fields carry the >= 30 threshold.
        "pop_day": pop_day,
        "pop_night": pop_night,
        "pop_day_display": _pop_display(pop_day),
        "pop_night_display": _pop_display(pop_night),
        # Per-half icons via the ensemble recipe.
        "icon_day": _ensemble_icon(
            pop_day, rain_med, snow_med, nt_day_p50, False, tt_high_p50,
        ),
        "icon_night": _ensemble_icon(
            pop_night, rain_med, snow_med, nt_night_p50, True, tt_low_p50,
        ),
        # Humidex feels-like per half (gated by EC convention).
        "feels_like_day": _humidex_feels_like(tt_high_p50, hmx_day_p50),
        "feels_like_night": _humidex_feels_like(tt_low_p50, hmx_night_p50),
        # Wet-day amount band (popup sentence only).
        "amount_band": amount_band,
    }


# ---------------------------------------------------------------------------
# A5 — outlook_sentence_params (parameters only; i18n lives in the card)
# ---------------------------------------------------------------------------

def outlook_sentence_params(
    tt_low_p25: float | None,
    tt_high_p75: float | None,
    pop_day: float | None,
    pop_night: float | None,
    amt_p25: float | None,
    amt_p75: float | None,
) -> dict:
    """Compute the parameters the card interpolates into the outlook sentence.

    Returns the rounded p25-low / p75-high range, the dominant (max) half POP,
    and the amount band — the band appears only when the dominant POP reaches
    50% (below that the median amount is drizzle-biased to zero). The card owns
    the actual localized sentence; this only supplies the numbers.
    """
    dominant_pop = max(
        (pop for pop in (pop_day, pop_night) if pop is not None),
        default=None,
    )

    amount_band = None
    if dominant_pop is not None and dominant_pop >= _POP_AMOUNT_MIN:
        amount_band = {"low": amt_p25, "high": amt_p75}

    return {
        "range_low": round(tt_low_p25) if tt_low_p25 is not None else None,
        "range_high": round(tt_high_p75) if tt_high_p75 is not None else None,
        "dominant_pop": round(dominant_pop) if dominant_pop is not None else None,
        "amount_band": amount_band,
    }


# ---------------------------------------------------------------------------
# Validation-harness classifiers (phase E)
# ---------------------------------------------------------------------------
# These bucket an icon code and a POP into the coarse families the validation
# harness scores agreement over. They live beside the recipe so the CI-able
# agreement tests and the dev-only live scorecard classify the WEonG reference
# and the GEPS-synthesized output identically. Pure and side-effect-free.

# icon code -> coarse weather family. Covers every code the WEonG derivation
# (``transforms.derive_icon``) and the GEPS ensemble recipe can produce, plus
# the neighbouring severity codes so the classifier is stable if a code widens.
_ICON_FAMILY: dict[int, str] = {
    SUNNY: "clear",
    MAINLY_SUNNY: "clear",
    CLEAR_NIGHT: "clear",
    MAINLY_CLEAR_NIGHT: "clear",
    PARTLY_CLOUDY_DAY: "partly",
    PARTLY_CLOUDY_NIGHT: "partly",
    MOSTLY_CLOUDY_DAY: "mostly",
    MOSTLY_CLOUDY_NIGHT: "mostly",
    CLOUDY: "cloudy",
    RAIN: "rain",
    RAIN_HEAVY: "rain",
    FREEZING_RAIN: "rain",
    THUNDERSTORM: "rain",
    11: "rain",  # ICON_CONDITIONS[11] == "rainy"
    SNOW: "snow",
    SNOW_LIGHT: "snow",
    SNOW_HEAVY: "snow",
    ICE_PELLETS: "snow",
    HAIL: "snow",
    _CHANCE_OF_SHOWERS: "chance-rain",
    _CHANCE_OF_FLURRIES: "chance-snow",
    RAIN_AND_SNOW: "mixed",
}

# Families that mean precipitation (wet). "chance-*" is wet-leaning: the recipe
# reaches it at 30-59% POP, the honest hedge between dry and a solid precip
# icon. "mixed" (rain and snow) is wet.
_WET_FAMILIES = frozenset({"rain", "snow", "chance-rain", "chance-snow", "mixed"})


def icon_family(code: int | None) -> str | None:
    """Return the coarse weather family for an EC icon code.

    One of: clear / partly / mostly / cloudy / rain / snow / chance-rain /
    chance-snow / mixed, or None when the code is None or unmapped.
    """
    if code is None:
        return None
    return _ICON_FAMILY.get(code)


def is_wet_family(family: str | None) -> bool:
    """Return True when a family means precipitation (incl. chance-of)."""
    return family in _WET_FAMILIES


def pop_band(pop: float | None) -> str | None:
    """Bucket a POP into the recipe's coarse bands.

    ``low`` (< 30, dry icon), ``chance`` (30-59, chance-of icon), ``likely``
    (>= 60, solid precip icon) — the same thresholds the ensemble icon recipe
    uses. None passes through as None.
    """
    if pop is None:
        return None
    if pop < _POP_CHANCE_ICON:
        return "low"
    if pop < _POP_PRECIP_ICON:
        return "chance"
    return "likely"
