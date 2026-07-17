"""GEPS extended-forecast fetch orchestration (phase B).

Phase B of the extended-forecast plan (specs/ec_weather/weong-far-days-plan.md):
the coordinator wave that brings days 4-6 popup timesteps back for everyone via
the GEPS ensemble. The pure synthesis (icon recipe, humidex gate, window
mapping) lives in ``extended_helpers``; this module owns the *planning* pieces
that turn a day's periods into GEPS queries and fold the raw values back into
``TimestepData`` plus the per-day ``precip_windows`` band payload.

Everything here is pure — no I/O, no hass, no network. ``ECWEonGCoordinator``
supplies the cached query executor and merges the results into its canonical
store, so GEPS lands beside HRDPS/RDPS and the store's model priority makes the
finer near-term sources win where they overlap (progressive refinement).

Live validation (Montreal test coords, 2026-07-07):
  - TT/HMX/NT p50 and PRMM ERGE1/ERC25/ERC75 return values via GetFeatureInfo.
  - RNMM/SNMM only publish at the 12h interval (the 3h variant phase A assumed
    returns InvalidLayersParameter) — corrected in ``extended_helpers``.
  - The 12h precip time dimension is PT12H anchored at 00Z/12Z, and a value
    labelled AT 12Z accumulates 00Z->12Z, confirming ``geps_window_for``.
  - GEPS runs at 00Z/12Z (reference_time dimension), with a ~5-6h publish lag.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from zoneinfo import ZoneInfo

from ..timestep_store import TimestepData
from .extended_helpers import (
    GEPS_AMOUNT_P25,
    GEPS_AMOUNT_P75,
    GEPS_CLOUD_P50,
    GEPS_HUMIDEX_P50,
    GEPS_POP_12H,
    GEPS_RAIN_MEDIAN,
    GEPS_SNOW_MEDIAN,
    GEPS_TEMPERATURE_P25,
    GEPS_TEMPERATURE_P50,
    GEPS_TEMPERATURE_P75,
    _period_bounds_utc,
    geps_window_for,
    outlook_day,
    outlook_sentence_params,
    synthesize_timestep,
)


# ---------------------------------------------------------------------------
# Extended-forecast coverage + scheduling constants
# ---------------------------------------------------------------------------

# GEPS 3h continuous-field cadence (TT/HMX/NT). Precip layers are 12h.
GEPS_STEP_HOURS = 3

# Calendar-day coverage for phase B: days_ahead 4-6 get GEPS timesteps. Day 3
# stays RDPS-only under the 84h cap; days 8+ are gated behind phase C's config.
EXTENDED_FIRST_DAY = 4
EXTENDED_LAST_DAY = 6

# Wet-gating: a 12h window's amount band + precip-type medians are only queried
# when its POP (PRMM ERGE1) reaches this percent — below it the amounts are
# drizzle-noise and the icon falls back to the cloud bucket anyway.
GEPS_WET_GATE_POP = 30

# GEPS model runs, in UTC, and the publish lag before a run's data is queryable.
GEPS_RUN_HOURS = (0, 12)
GEPS_PROCESSING_DELAY_H = 6  # ~5-6h lag; use the upper bound to avoid early misses

# Placeholder period key carried through the coordinator's cached query executor
# for GEPS queries. GEPS results are keyed back by (layer, timestep), not by
# period, so this tag is inert — it only satisfies the (layer, ts, key) shape.
GEPS_QUERY_TAG = ("geps", "")


def _iso_z(moment: datetime) -> str:
    """Format a UTC datetime as the store's ``...Z`` ISO string."""
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Coverage + scheduling helpers
# ---------------------------------------------------------------------------

def is_geps_day(days_ahead: int) -> bool:
    """Return True when a calendar day offset is inside the GEPS coverage band."""
    return EXTENDED_FIRST_DAY <= days_ahead <= EXTENDED_LAST_DAY


def days_ahead_for(date_str: str, today: date) -> int:
    """Return the whole-day offset of an ISO date from ``today`` (never negative)."""
    target = datetime.strptime(date_str, "%Y-%m-%d").date()
    return max(0, (target - today).days)


def expected_geps_run(now_utc: datetime) -> datetime:
    """Return the latest GEPS model run expected to be published by ``now_utc``.

    GEPS runs at 00Z/12Z and publishes ~5-6h later, so the 12Z run is queryable
    around 18Z. Before the first run of the day is available, the previous day's
    12Z run answers. The returned datetime is the run time, not availability.
    """
    availability = {run: run + GEPS_PROCESSING_DELAY_H for run in GEPS_RUN_HOURS}
    for run_hour in sorted(GEPS_RUN_HOURS, reverse=True):
        if now_utc.hour >= availability[run_hour]:
            return now_utc.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    # Before today's first run is available -> yesterday's last run (12Z).
    yesterday = now_utc - timedelta(days=1)
    return yesterday.replace(
        hour=max(GEPS_RUN_HOURS), minute=0, second=0, microsecond=0,
    )


# ---------------------------------------------------------------------------
# 3h timestep grid + 12h window mapping
# ---------------------------------------------------------------------------

def align_to_geps_grid(moment: datetime, step_h: int = GEPS_STEP_HOURS) -> datetime:
    """Round a UTC datetime UP to the next GEPS 3h grid point (anchored at 00Z).

    GEPS 3h fields are valid at 00,03,...,21Z. Period boundaries fall on whole
    local hours converted to UTC, so a boundary that is not already on the grid
    snaps forward to the first valid grid hour inside the period.
    """
    aligned = moment.replace(minute=0, second=0, microsecond=0)
    if aligned < moment:
        aligned += timedelta(hours=1)
    remainder = aligned.hour % step_h
    if remainder:
        aligned += timedelta(hours=step_h - remainder)
    return aligned


def geps_timesteps_for_periods(
    day_periods: list[tuple[str, str, datetime, datetime]],
    step_h: int = GEPS_STEP_HOURS,
) -> list[datetime]:
    """Return the GEPS 3h timesteps (UTC, grid-aligned) covering a day's periods.

    Steps are generated inside each ``[utc_start, utc_end)`` period and merged,
    so both the day and night halves of a calendar day are covered exactly once.
    """
    steps: set[datetime] = set()
    for _date_str, _period_type, utc_start, utc_end in day_periods:
        step = align_to_geps_grid(utc_start, step_h)
        while step < utc_end:
            steps.add(step)
            step += timedelta(hours=step_h)
    return sorted(steps)


def geps_windows_for_periods(
    day_periods: list[tuple[str, str, datetime, datetime]],
) -> list[dict]:
    """Map each local half of a day to its covering 12h GEPS window.

    Returns one entry per period (day/night half) as
    ``{"period_type", "start", "end"}`` where start/end are the UTC window
    bounds. The half's midpoint selects the window (via ``geps_window_for``), so
    each half aligns to exactly one 12h window regardless of the UTC offset.
    """
    windows: list[dict] = []
    for _date_str, period_type, utc_start, utc_end in day_periods:
        midpoint = utc_start + (utc_end - utc_start) / 2
        window_start, window_end = geps_window_for(midpoint)
        windows.append({
            "period_type": period_type,
            "start": window_start,
            "end": window_end,
        })
    return windows


def build_precip_window(
    window_start: datetime,
    window_end: datetime,
    pop: float | None,
    amount_p25: float | None,
    amount_p75: float | None,
) -> dict:
    """Build one ``precip_windows`` band entry for the daily-forecast attribute.

    The card's future-spanning precip vessels (phase D) read this: a 12h window
    with its POP and the p25/p75 amount band. ``amount_*`` stay None for dry
    windows (wet-gated), so the card renders a band only when there is one.
    """
    return {
        "start": _iso_z(window_start),
        "end": _iso_z(window_end),
        "pop": int(round(pop)) if pop is not None else None,
        # GEPS ERC25/ERC75 arrive as raw floats (e.g. 9.1000004); round to 1
        # decimal so the sensor attribute carries no float noise. None (a dry,
        # wet-gated window) stays None.
        "amount_p25": round(amount_p25, 1) if amount_p25 is not None else None,
        "amount_p75": round(amount_p75, 1) if amount_p75 is not None else None,
    }


# ---------------------------------------------------------------------------
# Query planning + result folding
# ---------------------------------------------------------------------------

def plan_base_queries(
    steps: list[datetime],
) -> list[tuple[str, datetime, tuple[str, str]]]:
    """The always-run GEPS queries: TT/HMX/NT p50 at each 3h step (3 per step)."""
    queries: list[tuple[str, datetime, tuple[str, str]]] = []
    for step in steps:
        queries.append((GEPS_TEMPERATURE_P50, step, GEPS_QUERY_TAG))
        queries.append((GEPS_HUMIDEX_P50, step, GEPS_QUERY_TAG))
        queries.append((GEPS_CLOUD_P50, step, GEPS_QUERY_TAG))
    return queries


def plan_pop_queries(
    window_ends: list[datetime],
) -> list[tuple[str, datetime, tuple[str, str]]]:
    """POP (PRMM ERGE1) at each covering 12h window end (00Z/12Z)."""
    return [(GEPS_POP_12H, end, GEPS_QUERY_TAG) for end in window_ends]


def plan_wet_queries(
    wet_window_ends: list[datetime],
) -> list[tuple[str, datetime, tuple[str, str]]]:
    """Amount band (ERC25/ERC75) + precip-type medians for wet windows only.

    RNMM/SNMM are 12h layers (verified live), so the precip-type call is per
    window, not per 3h step — it only feeds the wet/dry icon typing.
    """
    queries: list[tuple[str, datetime, tuple[str, str]]] = []
    for end in wet_window_ends:
        queries.append((GEPS_AMOUNT_P25, end, GEPS_QUERY_TAG))
        queries.append((GEPS_AMOUNT_P75, end, GEPS_QUERY_TAG))
        queries.append((GEPS_RAIN_MEDIAN, end, GEPS_QUERY_TAG))
        queries.append((GEPS_SNOW_MEDIAN, end, GEPS_QUERY_TAG))
    return queries


def wet_window_ends(pop_by_window_end: dict[datetime, float | None]) -> list[datetime]:
    """Return the window ends whose POP reaches the wet gate (>= 30)."""
    return sorted(
        end
        for end, pop in pop_by_window_end.items()
        if pop is not None and pop >= GEPS_WET_GATE_POP
    )


def index_results(
    results: list[tuple[str, datetime, tuple[str, str], float | None]],
) -> dict[tuple[str, datetime], float | None]:
    """Index cached-query results by ``(layer, timestep)`` for GEPS folding."""
    return {(layer, timestep): value for layer, timestep, _key, value in results}


def build_geps_timesteps(
    steps: list[datetime],
    pop_by_window_end: dict[datetime, float | None],
    values: dict[tuple[str, datetime], float | None],
) -> list[TimestepData]:
    """Fold GEPS query values into synthesized ``TimestepData`` per 3h step.

    Each step's POP is its covering 12h window's ERGE1 (stepwise by design);
    the precip-type medians come from that same window (RNMM/SNMM are 12h).
    """
    entries: list[TimestepData] = []
    for step in steps:
        _window_start, window_end = geps_window_for(step)
        window_pop = pop_by_window_end.get(window_end)
        entries.append(synthesize_timestep(
            _iso_z(step),
            values.get((GEPS_TEMPERATURE_P50, step)),
            values.get((GEPS_HUMIDEX_P50, step)),
            values.get((GEPS_CLOUD_P50, step)),
            window_pop,
            values.get((GEPS_RAIN_MEDIAN, window_end)),
            values.get((GEPS_SNOW_MEDIAN, window_end)),
        ))
    return entries


def build_precip_windows(
    half_windows: list[dict],
    pop_by_window_end: dict[datetime, float | None],
    values: dict[tuple[str, datetime], float | None],
) -> list[dict]:
    """Build the per-day ``precip_windows`` list (one band entry per half)."""
    windows: list[dict] = []
    for half in half_windows:
        window_end = half["end"]
        windows.append(build_precip_window(
            half["start"],
            window_end,
            pop_by_window_end.get(window_end),
            values.get((GEPS_AMOUNT_P25, window_end)),
            values.get((GEPS_AMOUNT_P75, window_end)),
        ))
    return windows


# ---------------------------------------------------------------------------
# Phase C — outlook coverage (days 8+ / calendar days beyond the official 7)
# ---------------------------------------------------------------------------

# First day offset that is an outlook day. The official citypage list covers
# day offsets 0-6 (7 calendar days); anything at offset 7+ is model outlook.
OUTLOOK_FIRST_DAY = 7

# Representative local hours for the daily extremes. Rather than sampling the
# whole 3h TT series per outlook day (8 queries/day — over the query budget at
# mode 14), we read the ensemble at the two hours the median diurnal cycle
# peaks and troughs: mid-afternoon for the daytime high, pre-dawn for the
# overnight low. At outlook range (day 8+) the sub-daily *timing* is not
# resolvable anyway; sampling a single hour per half keeps the band honest —
# p25/p75 are the true ensemble spread AT that hour, not a cross-hour artifact.
OUTLOOK_DAY_PEAK_HOUR = 15      # local — daytime high
OUTLOOK_NIGHT_TROUGH_HOUR = 5   # local, next calendar day — overnight low


def outlook_days_ahead(forecast_days: int) -> list[int]:
    """Return the day offsets that get an outlook entry for a config mode.

    Mode 7 (default) -> none. Mode 10 -> offsets 7,8,9 (calendar days 8-10).
    Mode 14 -> offsets 7..13 (calendar days 8-14).
    """
    return list(range(OUTLOOK_FIRST_DAY, forecast_days))


def is_outlook_day(days_ahead: int, forecast_days: int) -> bool:
    """Return True when a day offset is an outlook day for the given mode."""
    return OUTLOOK_FIRST_DAY <= days_ahead < forecast_days


def outlook_dates(today: date, forecast_days: int) -> list[str]:
    """Return the ISO dates (beyond the official 7) that get an outlook entry."""
    return [
        (today + timedelta(days=offset)).isoformat()
        for offset in outlook_days_ahead(forecast_days)
    ]


def nearest_geps_step(moment: datetime, step_h: int = GEPS_STEP_HOURS) -> datetime:
    """Round a UTC datetime to the NEAREST GEPS 3h grid point (anchored at 00Z).

    Unlike ``align_to_geps_grid`` (which ceils into a period), the outlook
    representative hour wants the closest grid step to a target local hour, so
    the sampled diurnal peak/trough lands on the nearest available 3h value.
    """
    midnight = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    hours_from_midnight = (moment - midnight).total_seconds() / 3600
    nearest = round(hours_from_midnight / step_h) * step_h
    return midnight + timedelta(hours=nearest)


def outlook_sample_points(date_str: str, local_tz: ZoneInfo) -> dict:
    """Return the GEPS sample points for one outlook calendar day.

    ``day_rep``/``night_rep`` are the 3h grid steps nearest the local diurnal
    peak/trough (the continuous-field sample hours). ``day_window_end`` and
    ``night_window_end`` are the 12h POP/precip windows covering each local
    half, selected by the half's midpoint (same convention as
    ``geps_windows_for_periods``).
    """
    year, month, day = (int(part) for part in date_str.split("-"))
    next_day = date(year, month, day) + timedelta(days=1)

    peak_local = datetime(
        year, month, day, OUTLOOK_DAY_PEAK_HOUR, tzinfo=local_tz,
    )
    trough_local = datetime(
        next_day.year, next_day.month, next_day.day,
        OUTLOOK_NIGHT_TROUGH_HOUR, tzinfo=local_tz,
    )
    day_rep = nearest_geps_step(peak_local.astimezone(timezone.utc))
    night_rep = nearest_geps_step(trough_local.astimezone(timezone.utc))

    day_start, day_end = _period_bounds_utc(date_str, "day", local_tz)
    night_start, night_end = _period_bounds_utc(date_str, "night", local_tz)
    _, day_window_end = geps_window_for(day_start + (day_end - day_start) / 2)
    _, night_window_end = geps_window_for(night_start + (night_end - night_start) / 2)

    return {
        "day_rep": day_rep,
        "night_rep": night_rep,
        "day_window_end": day_window_end,
        "night_window_end": night_window_end,
    }


def plan_outlook_base_queries(
    day_rep: datetime,
    night_rep: datetime,
) -> list[tuple[str, datetime, tuple[str, str]]]:
    """The always-run outlook queries: continuous fields at the two rep hours.

    Day rep carries the warm-side band (TT p75); night rep the cold-side band
    (TT p25). Both carry TT/HMX/NT p50. Ten queries total per outlook day once
    the two POP windows are added (see ``plan_pop_queries``).
    """
    return [
        (GEPS_TEMPERATURE_P50, day_rep, GEPS_QUERY_TAG),
        (GEPS_TEMPERATURE_P75, day_rep, GEPS_QUERY_TAG),
        (GEPS_HUMIDEX_P50, day_rep, GEPS_QUERY_TAG),
        (GEPS_CLOUD_P50, day_rep, GEPS_QUERY_TAG),
        (GEPS_TEMPERATURE_P50, night_rep, GEPS_QUERY_TAG),
        (GEPS_TEMPERATURE_P25, night_rep, GEPS_QUERY_TAG),
        (GEPS_HUMIDEX_P50, night_rep, GEPS_QUERY_TAG),
        (GEPS_CLOUD_P50, night_rep, GEPS_QUERY_TAG),
    ]


def _dominant_wet_precip(
    pop_day: float | None,
    pop_night: float | None,
    day_window_end: datetime,
    night_window_end: datetime,
    values: dict[tuple[str, datetime], float | None],
) -> tuple[float | None, float | None, float | None, float | None]:
    """Pick the amount band + precip-type medians from the wetter half's window.

    ``outlook_day`` types both half icons from a single rain/snow median pair;
    at outlook range the wet/dry regime is stable across a day, so the wettest
    window (highest POP at/above the wet gate) sources the band and type.
    Returns ``(amt_p25, amt_p75, rain_med, snow_med)`` — all None when neither
    half reaches the wet gate.
    """
    candidates: list[tuple[float, datetime]] = []
    if pop_day is not None and pop_day >= GEPS_WET_GATE_POP:
        candidates.append((pop_day, day_window_end))
    if pop_night is not None and pop_night >= GEPS_WET_GATE_POP:
        candidates.append((pop_night, night_window_end))
    if not candidates:
        return None, None, None, None

    _, window_end = max(candidates, key=lambda item: item[0])
    return (
        values.get((GEPS_AMOUNT_P25, window_end)),
        values.get((GEPS_AMOUNT_P75, window_end)),
        values.get((GEPS_RAIN_MEDIAN, window_end)),
        values.get((GEPS_SNOW_MEDIAN, window_end)),
    )


def build_outlook_entry(
    date_str: str,
    points: dict,
    pop_by_window_end: dict[datetime, float | None],
    values: dict[tuple[str, datetime], float | None],
) -> dict:
    """Fold outlook query values into a daily-forecast outlook entry.

    Wraps ``outlook_day`` (medians as scalars, p25/p75 band, per-half icons,
    ``source: "outlook"``, no dishonest keys) and attaches:
      - ``period`` (mirrors the official rows' key),
      - ``sentence`` — the ``outlook_sentence_params`` payload the card
        interpolates into the localized outlook sentence,
      - ``timesteps_state: "outlook"`` — outlook days have no timeline at all;
        the explicit state plus the absence of any ``timesteps_*`` list is the
        honest representation (distinct from "pending"/"unavailable").
    """
    day_rep = points["day_rep"]
    night_rep = points["night_rep"]
    day_window_end = points["day_window_end"]
    night_window_end = points["night_window_end"]

    pop_day = pop_by_window_end.get(day_window_end)
    pop_night = pop_by_window_end.get(night_window_end)

    amt_p25, amt_p75, rain_med, snow_med = _dominant_wet_precip(
        pop_day, pop_night, day_window_end, night_window_end, values,
    )

    tt_low_p25 = values.get((GEPS_TEMPERATURE_P25, night_rep))
    tt_high_p75 = values.get((GEPS_TEMPERATURE_P75, day_rep))

    entry = outlook_day(
        date_str,
        tt_low_p25=tt_low_p25,
        tt_low_p50=values.get((GEPS_TEMPERATURE_P50, night_rep)),
        tt_high_p50=values.get((GEPS_TEMPERATURE_P50, day_rep)),
        tt_high_p75=tt_high_p75,
        pop_day=pop_day,
        pop_night=pop_night,
        amt_p25=amt_p25,
        amt_p75=amt_p75,
        nt_day_p50=values.get((GEPS_CLOUD_P50, day_rep)),
        nt_night_p50=values.get((GEPS_CLOUD_P50, night_rep)),
        rain_med=rain_med,
        snow_med=snow_med,
        hmx_day_p50=values.get((GEPS_HUMIDEX_P50, day_rep)),
        hmx_night_p50=values.get((GEPS_HUMIDEX_P50, night_rep)),
    )
    entry["period"] = date_str
    entry["sentence"] = outlook_sentence_params(
        tt_low_p25=tt_low_p25,
        tt_high_p75=tt_high_p75,
        pop_day=pop_day,
        pop_night=pop_night,
        amt_p25=amt_p25,
        amt_p75=amt_p75,
    )
    entry["timesteps_state"] = "outlook"
    return entry
