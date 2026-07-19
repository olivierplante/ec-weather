"""Canonical timestep store — single source of truth for WEonG data.

Replaces the dual periods{} + hourly{} data structure with an append-only
(merge-with-override) store keyed by ISO UTC timestamp. All views
(hourly scroll, daily columns, popup timeline) are read-only projections
of this store.

Design principles:
- One source of truth: no parallel data shapes
- Append-only: new data enriches existing timesteps, never wipes them
- HRDPS preferred: HRDPS data is not overwritten by RDPS
- SkyState survives: lazy-fetched SkyState persists across refreshes
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timezone


# Fields that go into the public dict output.
# sky_state is included because transforms.py reads it for icon derivation
# (and strips it after use).
_PUBLIC_FIELDS_MAP = {
    "time": "time",
    "temp": "temp",
    "feels_like": "feels_like",
    "icon_code": "icon_code",
    "condition": "condition",
    "pop": "precipitation_probability",
    "rain_mm": "rain_mm",
    "snow_cm": "snow_cm",
    "freezing_precip_mm": "freezing_precip_mm",
    "ice_pellet_cm": "ice_pellet_cm",
    "wind_speed": "wind_speed",
    "wind_gust": "wind_gust",
    "wind_direction": "wind_direction",
    "sky_state": "sky_state",
}


@dataclass
class TimestepData:
    """Data for a single timestep in the canonical store.

    All fields except `time` are optional and default to None.
    `model` and `model_run` are internal (not in public output).
    `sky_state` is included in public output because transforms.py
    reads it for icon derivation and strips it after use.
    """

    time: str  # ISO UTC timestamp (store key)

    # Weather data (public)
    temp: float | None = None
    feels_like: float | None = None
    icon_code: int | None = None
    condition: str | None = None
    pop: int | None = None
    rain_mm: float | None = None
    snow_cm: float | None = None
    freezing_precip_mm: float | None = None
    ice_pellet_cm: float | None = None
    wind_speed: float | None = None
    wind_gust: float | None = None
    wind_direction: str | None = None

    # Internal (for icon derivation and cache management)
    sky_state: float | None = None
    model: str | None = None  # "hrdps" or "rdps"
    model_run: str | None = None  # reference_datetime

    def to_dict(self) -> dict:
        """Convert to a public-facing dict, stripping internal fields."""
        return {
            output_key: getattr(self, attr_name)
            for attr_name, output_key in _PUBLIC_FIELDS_MAP.items()
        }

    def to_hourly_dict(self) -> dict:
        """Convert to hourly output format (includes sky_state for icon derivation)."""
        return {
            "rain_mm": self.rain_mm,
            "snow_cm": self.snow_cm,
            "freezing_precip_mm": self.freezing_precip_mm,
            "ice_pellet_cm": self.ice_pellet_cm,
            "sky_state": self.sky_state,
            "temp": self.temp,
            "precipitation_probability": self.pop,
        }

    def to_storage_dict(self) -> dict:
        """Serialize every field (including internal model/model_run/sky_state).

        Distinct from ``to_dict``: that one strips internals for card output;
        this one round-trips the full dataclass through JSON for the persistent
        cache. All fields are str/float/int/None, so the result is JSON-safe.
        """
        return {field.name: getattr(self, field.name) for field in fields(self)}

    @classmethod
    def from_storage_dict(cls, data: dict) -> "TimestepData":
        """Rebuild a TimestepData from ``to_storage_dict`` output.

        Unknown keys (a future schema minor add) are ignored so an older reader
        does not crash; ``time`` is required and always present.
        """
        known = {field.name for field in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})


def aggregate_expected_precip(
    entries: list[tuple[int | float | None, float | None, float | None]],
) -> tuple[int | None, float | None, float | None]:
    """Aggregate a set of timesteps into (pop_max, rain_mm, snow_cm).

    ``entries`` is an iterable of ``(pop, rain_mm, snow_cm)`` triples. The
    returned values follow the period-projection semantics:

    - pop: max POP across the timesteps (or None if none carry a POP).
    - rain_mm / snow_cm: probability-weighted EXPECTED totals. The per-timestep
      WEonG amounts are conditional ("amount GIVEN precip that hour"), so each
      timestep contributes ``(pop/100) * amount`` and those are summed. A
      null-POP timestep contributes nothing (no defensible expectation).
    - Trace floor: an expected total below 1.0 mm rain / 0.5 cm snow is reported
      as None — EC discards sub-0.1 mm/h WEonG noise, so a sub-measurable daily
      expectation is noise too and would only mislead.

    This is the single source of the aggregation math so the fetch-time period
    projection (:meth:`TimestepStore.project_periods`) and the render-time
    remaining-window recompute (``transforms.apply_remaining_only``) always
    agree for the same set of timesteps.
    """
    pops = [pop for pop, _rain, _snow in entries if pop is not None]
    pop_max = int(round(max(pops))) if pops else None

    rain_expected = 0.0
    has_rain = False
    snow_expected = 0.0
    has_snow = False

    for pop, rain_mm, snow_cm in entries:
        # A null-POP timestep contributes nothing: with no probability there is
        # no defensible expectation, and inventing one would re-inflate totals.
        if pop is None:
            continue
        probability = pop / 100.0
        if rain_mm is not None and rain_mm > 0:
            rain_expected += probability * rain_mm
            has_rain = True
        if snow_cm is not None and snow_cm > 0:
            snow_expected += probability * snow_cm
            has_snow = True

    rain_total = round(rain_expected, 1) if has_rain else None
    snow_total = round(snow_expected, 1) if has_snow else None

    # Trace floor: sub-measurable expectations are noise, not actionable amounts.
    if rain_total is not None and rain_total < 1.0:
        rain_total = None
    if snow_total is not None and snow_total < 0.5:
        snow_total = None

    return pop_max, rain_total, snow_total


# Model preference: HRDPS > RDPS > GEPS. Finer, nearer-term sources win where
# they overlap the extended GEPS ensemble, so progressive refinement is
# automatic — as a date nears, RDPS-WEonG overwrites the coarse GEPS synthesis.
_MODEL_PRIORITY = {"hrdps": 3, "rdps": 2, "geps": 1}

# Merge-eligible fields (all fields except time, which is the key)
_MERGE_FIELDS = [
    f.name for f in fields(TimestepData) if f.name != "time"  # type: ignore[arg-type]
]


class TimestepStore:
    """Canonical timestep store with merge-with-override semantics.

    The store is a dict keyed by ISO UTC timestamp string. Each entry
    is a TimestepData instance. Merging new data into an existing entry
    follows these rules:

    1. New non-None values overwrite existing values
    2. None values do NOT overwrite existing non-None values
    3. HRDPS data is never overwritten by RDPS data
    4. RDPS can fill in null fields of an existing HRDPS entry
    """

    def __init__(self) -> None:
        self._entries: dict[str, TimestepData] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, time_key: str) -> TimestepData | None:
        """Get a timestep entry by ISO timestamp key."""
        return self._entries.get(time_key)

    def merge(self, new: TimestepData) -> None:
        """Merge a TimestepData into the store.

        If no entry exists for this timestamp, the new data is inserted.
        If an entry exists, fields are merged according to the rules:
        - None values in new don't overwrite existing non-None values
        - RDPS doesn't overwrite existing HRDPS data
        - RDPS can fill in null fields of an existing HRDPS entry
        """
        existing = self._entries.get(new.time)
        if existing is None:
            self._entries[new.time] = new
            return

        # Determine model preference
        existing_priority = _MODEL_PRIORITY.get(existing.model or "", 0)
        new_priority = _MODEL_PRIORITY.get(new.model or "", 0)

        # If existing is HRDPS and new is RDPS, only fill null fields
        rdps_filling_hrdps = (
            existing_priority > new_priority
            and new.model is not None
            and existing.model is not None
        )

        for field_name in _MERGE_FIELDS:
            new_val = getattr(new, field_name)
            existing_val = getattr(existing, field_name)

            if new_val is None:
                continue  # Rule 2: None doesn't overwrite

            if rdps_filling_hrdps:
                # Rule 4: RDPS can only fill null fields
                if existing_val is not None and field_name != "model":
                    continue
                # Don't overwrite model field with the lower-priority model
                if field_name == "model":
                    continue
                setattr(existing, field_name, new_val)
            else:
                # Rule 1: new non-None overwrites, or
                # Rule 3: HRDPS overwrites RDPS
                setattr(existing, field_name, new_val)

    def merge_batch(self, entries: list[TimestepData]) -> None:
        """Merge multiple entries into the store."""
        for entry in entries:
            self.merge(entry)

    def prune_before(self, cutoff: str) -> None:
        """Remove entries with timestamp strictly before cutoff."""
        stale_keys = [k for k in self._entries if k < cutoff]
        for key in stale_keys:
            del self._entries[key]

    def to_storage_list(self) -> list[dict]:
        """Serialize all entries for the persistent cache (unordered)."""
        return [entry.to_storage_dict() for entry in self._entries.values()]

    def load_storage_list(self, items: list[dict]) -> None:
        """Restore entries from ``to_storage_list`` output.

        Keys are unique per timestamp, so entries are inserted directly. Called
        on an empty store at restore time.
        """
        for item in items:
            entry = TimestepData.from_storage_dict(item)
            self._entries[entry.time] = entry

    def project_periods(
        self,
        periods: list[tuple[str, str, datetime, datetime]],
    ) -> dict[tuple[str, str], dict]:
        """Project the store into day/night period groups.

        Each period is (date_str, period_type, utc_start, utc_end).
        Returns a dict keyed by (date_str, period_type) with:
        - pop: max POP across timesteps (or None)
        - rain_mm: probability-weighted expected rain total (or None)
        - snow_cm: probability-weighted expected snow total (or None)
        - timesteps: list of timestep dicts (public fields only)

        The per-timestep WEonG amounts are CONDITIONAL ("amount GIVEN precip
        occurs that hour"), so summing them inflates totals on low-POP days.
        The period total is instead the EXPECTED amount: each timestep
        contributes (pop/100) * amount, summed over the period. The per-hour
        amounts in the ``timesteps`` list are left untouched — those surfaces
        show the conditional amounts by design.
        """
        result: dict[tuple[str, str], dict] = {}

        for date_str, period_type, utc_start, utc_end in periods:
            key = (date_str, period_type)
            start_str = utc_start.strftime("%Y-%m-%dT%H:%M:%SZ")
            end_str = utc_end.strftime("%Y-%m-%dT%H:%M:%SZ")

            # Collect timesteps within this period's time range
            period_entries: list[TimestepData] = []
            for ts_key, entry in self._entries.items():
                if start_str <= ts_key < end_str:
                    period_entries.append(entry)

            period_entries.sort(key=lambda e: e.time)

            if not period_entries:
                result[key] = {
                    "pop": None,
                    "rain_mm": None,
                    "snow_cm": None,
                    "timesteps": [],
                }
                continue

            # Aggregate over the full period window. The in-progress period is
            # re-aggregated at render time over its REMAINING timesteps only
            # (transforms.apply_remaining_only), which reuses this same math so
            # the two never diverge for the same set of timesteps.
            pop_max, rain_total, snow_total = aggregate_expected_precip(
                [(e.pop, e.rain_mm, e.snow_cm) for e in period_entries]
            )

            result[key] = {
                "pop": pop_max,
                "rain_mm": rain_total,
                "snow_cm": snow_total,
                "timesteps": [e.to_dict() for e in period_entries],
            }

        return result

    def project_hourly(self, horizon_end: str | None = None) -> dict[str, dict]:
        """Project the store into hourly output format.

        Returns a dict keyed by ISO timestamp with per-hour weather data for the
        hourly strip. Membership is decided by TIME, not model identity: any hour
        the store can serve is served identically to every consumer, so a
        near-term RDPS hour that HRDPS did not cover shows on the strip exactly
        as it does in the daily popup (no consumer-side source divergence).

        ``horizon_end`` (ISO UTC) bounds the near-term view: entries at or after
        it are excluded. This preserves the original HRDPS-only filter's intent —
        keeping coarse far-day RDPS/GEPS data out of the near-term scroll — via a
        time bound rather than a model filter. When None (direct/legacy callers),
        no upper bound is applied.
        """
        result: dict[str, dict] = {}
        for ts_key, entry in self._entries.items():
            if horizon_end is not None and ts_key >= horizon_end:
                continue
            result[ts_key] = entry.to_hourly_dict()
        return result
