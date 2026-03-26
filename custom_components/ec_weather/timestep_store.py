"""Canonical timestep store — single source of truth for WEonG data.

Replaces the dual periods{} + hourly{} data structure with an append-only
(merge-with-override) store keyed by ISO UTC timestamp. All views
(hourly scroll, daily columns, popup timeline) are read-only projections
of this store.

Design principles:
- One source of truth: no parallel data shapes
- Append-only: new data enriches existing timesteps, never wipes them
- HRDPS preferred: HRDPS data is not overwritten by GDPS
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
    model: str | None = None  # "hrdps" or "gdps"
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


# Model preference: HRDPS > GDPS
_MODEL_PRIORITY = {"hrdps": 2, "gdps": 1}

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
    3. HRDPS data is never overwritten by GDPS data
    4. GDPS can fill in null fields of an existing HRDPS entry
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
        - GDPS doesn't overwrite existing HRDPS data
        - GDPS can fill in null fields of an existing HRDPS entry
        """
        existing = self._entries.get(new.time)
        if existing is None:
            self._entries[new.time] = new
            return

        # Determine model preference
        existing_priority = _MODEL_PRIORITY.get(existing.model or "", 0)
        new_priority = _MODEL_PRIORITY.get(new.model or "", 0)

        # If existing is HRDPS and new is GDPS, only fill null fields
        gdps_filling_hrdps = (
            existing_priority > new_priority
            and new.model is not None
            and existing.model is not None
        )

        for field_name in _MERGE_FIELDS:
            new_val = getattr(new, field_name)
            existing_val = getattr(existing, field_name)

            if new_val is None:
                continue  # Rule 2: None doesn't overwrite

            if gdps_filling_hrdps:
                # Rule 4: GDPS can only fill null fields
                if existing_val is not None and field_name != "model":
                    continue
                # Don't overwrite model field with gdps
                if field_name == "model":
                    continue
                setattr(existing, field_name, new_val)
            else:
                # Rule 1: new non-None overwrites, or
                # Rule 3: HRDPS overwrites GDPS
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

    def project_periods(
        self,
        periods: list[tuple[str, str, datetime, datetime]],
    ) -> dict[tuple[str, str], dict]:
        """Project the store into day/night period groups.

        Each period is (date_str, period_type, utc_start, utc_end).
        Returns a dict keyed by (date_str, period_type) with:
        - pop: max POP across timesteps (or None)
        - rain_mm: sum of rain (or None if all zero/null)
        - snow_cm: sum of snow (or None if all zero/null)
        - timesteps: list of timestep dicts (public fields only)
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

            # Aggregate
            pops = [e.pop for e in period_entries if e.pop is not None]
            pop_max = int(round(max(pops))) if pops else None

            rain_sum = 0.0
            has_rain = False
            snow_sum = 0.0
            has_snow = False

            for entry in period_entries:
                if entry.rain_mm is not None and entry.rain_mm > 0:
                    rain_sum += entry.rain_mm
                    has_rain = True
                if entry.snow_cm is not None and entry.snow_cm > 0:
                    snow_sum += entry.snow_cm
                    has_snow = True

            result[key] = {
                "pop": pop_max,
                "rain_mm": round(rain_sum, 1) if has_rain else None,
                "snow_cm": round(snow_sum, 1) if has_snow else None,
                "timesteps": [e.to_dict() for e in period_entries],
            }

        return result

    def project_hourly(self) -> dict[str, dict]:
        """Project the store into hourly output format.

        Returns dict keyed by ISO timestamp with weather data for
        the hourly scroll. Only includes HRDPS entries (1h resolution)
        since GDPS (3h) would create gaps in the hourly view.
        """
        result: dict[str, dict] = {}
        for ts_key, entry in self._entries.items():
            if entry.model == "gdps":
                continue  # Skip GDPS for hourly view
            result[ts_key] = entry.to_hourly_dict()
        return result
