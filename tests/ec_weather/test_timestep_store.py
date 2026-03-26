"""Tests for the canonical timestep store — Phase B.

The TimestepStore is the single source of truth for all WEonG data.
It replaces the dual periods{} + hourly{} data structure with an
append-only (merge-with-override) store keyed by ISO UTC timestamp.

Tests verify:
1. Merge semantics: new data enriches, never wipes
2. None values don't overwrite existing values
3. Newer model run overwrites older values
4. Period projection: correct day/night grouping
5. Hourly projection: correct filtering
6. SkyState update: modifies store entry
7. Progressive loading: store grows incrementally, no data loss
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ec_weather.timestep_store import TimestepData, TimestepStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(hour: int, day: int = 22) -> str:
    """Build an ISO UTC timestamp string for 2026-03-{day}T{hour}:00:00Z."""
    return f"2026-03-{day:02d}T{hour:02d}:00:00Z"


def _make_store() -> TimestepStore:
    """Create an empty store."""
    return TimestepStore()


# ---------------------------------------------------------------------------
# TimestepData basics
# ---------------------------------------------------------------------------

class TestTimestepData:
    """Tests for the TimestepData dataclass."""

    def test_defaults_are_none(self):
        """All optional fields default to None."""
        data = TimestepData(time=_ts(12))
        assert data.temp is None
        assert data.pop is None
        assert data.icon_code is None
        assert data.rain_mm is None
        assert data.snow_cm is None
        assert data.sky_state is None
        assert data.model is None
        assert data.model_run is None

    def test_fields_set_on_creation(self):
        """Fields set at creation are stored."""
        data = TimestepData(time=_ts(12), temp=-3.5, pop=60, model="hrdps")
        assert data.temp == -3.5
        assert data.pop == 60
        assert data.model == "hrdps"

    def test_to_dict_excludes_internal_fields(self):
        """to_dict() strips model and model_run from output but keeps sky_state."""
        data = TimestepData(
            time=_ts(12), temp=-3.5, pop=60, sky_state=5.0,
            model="hrdps", model_run="2026-03-22T00:00:00Z",
        )
        result = data.to_dict()
        assert "model" not in result
        assert "model_run" not in result
        # sky_state IS included (needed by transforms.py for icon derivation)
        assert result["sky_state"] == 5.0
        assert result["time"] == _ts(12)
        assert result["temp"] == -3.5

    def test_to_dict_includes_all_public_fields(self):
        """to_dict() includes all weather data fields."""
        data = TimestepData(time=_ts(12))
        result = data.to_dict()
        expected_keys = {
            "time", "temp", "feels_like", "icon_code", "condition",
            "precipitation_probability",
            "rain_mm", "snow_cm", "freezing_precip_mm", "ice_pellet_cm",
            "wind_speed", "wind_gust", "wind_direction",
            "sky_state",
        }
        assert set(result.keys()) == expected_keys


# ---------------------------------------------------------------------------
# Store merge semantics
# ---------------------------------------------------------------------------

class TestStoreMerge:
    """Tests for TimestepStore.merge() — core merge-with-override semantics."""

    def test_merge_new_entry(self):
        """Merging a new timestep adds it to the store."""
        store = _make_store()
        store.merge(TimestepData(time=_ts(12), temp=-3.0, pop=60))

        entry = store.get(_ts(12))
        assert entry is not None
        assert entry.temp == -3.0
        assert entry.pop == 60

    def test_merge_enriches_existing(self):
        """Merging new fields into an existing entry enriches it."""
        store = _make_store()
        store.merge(TimestepData(time=_ts(12), temp=-3.0))
        store.merge(TimestepData(time=_ts(12), pop=60, rain_mm=2.5))

        entry = store.get(_ts(12))
        assert entry.temp == -3.0  # preserved from first merge
        assert entry.pop == 60  # added by second merge
        assert entry.rain_mm == 2.5  # added by second merge

    def test_merge_none_does_not_overwrite(self):
        """Merging None values does NOT overwrite existing non-None values."""
        store = _make_store()
        store.merge(TimestepData(time=_ts(12), temp=-3.0, pop=60))
        store.merge(TimestepData(time=_ts(12), temp=None, pop=None, rain_mm=1.0))

        entry = store.get(_ts(12))
        assert entry.temp == -3.0  # NOT overwritten by None
        assert entry.pop == 60  # NOT overwritten by None
        assert entry.rain_mm == 1.0  # new field added

    def test_merge_overwrites_with_non_none(self):
        """Merging non-None values overwrites existing values."""
        store = _make_store()
        store.merge(TimestepData(time=_ts(12), temp=-3.0))
        store.merge(TimestepData(time=_ts(12), temp=-5.0))

        entry = store.get(_ts(12))
        assert entry.temp == -5.0  # overwritten with newer value

    def test_merge_model_run_update(self):
        """Newer model run overwrites all fields from the new entry."""
        store = _make_store()
        store.merge(TimestepData(
            time=_ts(12), temp=-3.0, pop=30,
            model="hrdps", model_run="2026-03-22T00:00:00Z",
        ))
        store.merge(TimestepData(
            time=_ts(12), temp=-5.0, pop=60,
            model="hrdps", model_run="2026-03-22T06:00:00Z",
        ))

        entry = store.get(_ts(12))
        assert entry.temp == -5.0
        assert entry.pop == 60
        assert entry.model_run == "2026-03-22T06:00:00Z"

    def test_merge_same_model_run_enriches(self):
        """Same model run: enriches existing entry without wiping."""
        store = _make_store()
        store.merge(TimestepData(
            time=_ts(12), temp=-3.0,
            model="hrdps", model_run="2026-03-22T00:00:00Z",
        ))
        store.merge(TimestepData(
            time=_ts(12), pop=60,
            model="hrdps", model_run="2026-03-22T00:00:00Z",
        ))

        entry = store.get(_ts(12))
        assert entry.temp == -3.0  # preserved
        assert entry.pop == 60  # enriched

    def test_merge_hrdps_preferred_over_gdps(self):
        """HRDPS data is preferred over GDPS for the same timestep."""
        store = _make_store()
        store.merge(TimestepData(
            time=_ts(12), temp=-3.0, model="gdps",
        ))
        store.merge(TimestepData(
            time=_ts(12), temp=-5.0, model="hrdps",
        ))

        entry = store.get(_ts(12))
        assert entry.temp == -5.0
        assert entry.model == "hrdps"

    def test_merge_gdps_does_not_overwrite_hrdps(self):
        """GDPS data does NOT overwrite existing HRDPS data."""
        store = _make_store()
        store.merge(TimestepData(
            time=_ts(12), temp=-5.0, model="hrdps",
        ))
        store.merge(TimestepData(
            time=_ts(12), temp=-3.0, model="gdps",
        ))

        entry = store.get(_ts(12))
        assert entry.temp == -5.0  # HRDPS preserved
        assert entry.model == "hrdps"

    def test_gdps_enriches_null_fields_of_hrdps(self):
        """GDPS can fill in null fields of an existing HRDPS entry."""
        store = _make_store()
        store.merge(TimestepData(
            time=_ts(12), temp=-5.0, model="hrdps",
        ))
        store.merge(TimestepData(
            time=_ts(12), pop=40, model="gdps",
        ))

        entry = store.get(_ts(12))
        assert entry.temp == -5.0  # HRDPS preserved
        assert entry.pop == 40  # GDPS filled the gap
        assert entry.model == "hrdps"  # model stays as preferred

    def test_merge_multiple_timesteps(self):
        """Merging data for different timestamps creates separate entries."""
        store = _make_store()
        store.merge(TimestepData(time=_ts(12), temp=-3.0))
        store.merge(TimestepData(time=_ts(13), temp=-4.0))
        store.merge(TimestepData(time=_ts(14), temp=-5.0))

        assert len(store) == 3
        assert store.get(_ts(12)).temp == -3.0
        assert store.get(_ts(13)).temp == -4.0
        assert store.get(_ts(14)).temp == -5.0


# ---------------------------------------------------------------------------
# Progressive loading — store grows, never wipes
# ---------------------------------------------------------------------------

class TestProgressiveLoading:
    """Verify the store handles progressive loading correctly."""

    def test_progressive_merge_preserves_earlier_data(self):
        """Merging day 1 data then day 2 data preserves day 1."""
        store = _make_store()
        # Day 1 data
        for hour in range(11, 23):
            store.merge(TimestepData(time=_ts(hour, day=22), pop=30))

        # Day 2 data arrives
        for hour in range(11, 23):
            store.merge(TimestepData(time=_ts(hour, day=23), pop=50))

        # Both days present
        assert store.get(_ts(12, day=22)).pop == 30
        assert store.get(_ts(12, day=23)).pop == 50
        assert len(store) == 24

    def test_sky_state_merge_into_existing_timestep(self):
        """SkyState lazy fetch merges into existing timestep data."""
        store = _make_store()
        # Phase 1+2 data
        store.merge(TimestepData(
            time=_ts(12), temp=-3.0, pop=30, rain_mm=0,
        ))
        # Phase 3 lazy fetch adds SkyState
        store.merge(TimestepData(time=_ts(12), sky_state=5.0))

        entry = store.get(_ts(12))
        assert entry.temp == -3.0  # preserved
        assert entry.pop == 30  # preserved
        assert entry.sky_state == 5.0  # added

    def test_sky_state_survives_full_refresh(self):
        """SkyState from lazy fetch persists when Phase 1+2 data refreshes."""
        store = _make_store()
        # Initial Phase 1+2 + Phase 3
        store.merge(TimestepData(time=_ts(12), temp=-3.0, pop=30))
        store.merge(TimestepData(time=_ts(12), sky_state=5.0))

        # Full refresh (Phase 1+2 again) — sky_state should survive
        store.merge(TimestepData(time=_ts(12), temp=-4.0, pop=40))

        entry = store.get(_ts(12))
        assert entry.temp == -4.0  # updated
        assert entry.pop == 40  # updated
        assert entry.sky_state == 5.0  # preserved from lazy fetch


# ---------------------------------------------------------------------------
# Period projection
# ---------------------------------------------------------------------------

class TestPeriodProjection:
    """Tests for projecting the store into day/night period groups."""

    def test_group_by_day_night(self):
        """Timesteps grouped correctly into day (06-18 local) and night (18-06)."""
        store = _make_store()
        # Day: 11:00-22:00 UTC = 07:00-18:00 EDT (day period)
        for hour in range(11, 22):
            store.merge(TimestepData(time=_ts(hour, day=22), pop=30))
        # Night: 22:00 UTC = 18:00 EDT (night period start)
        for hour in range(22, 24):
            store.merge(TimestepData(time=_ts(hour, day=22), pop=20))

        periods = [
            ("2026-03-22", "day", _utc(10, 22), _utc(22, 22)),
            ("2026-03-22", "night", _utc(22, 22), _utc(10, 23)),
        ]
        projection = store.project_periods(periods)

        day_data = projection[("2026-03-22", "day")]
        night_data = projection[("2026-03-22", "night")]

        # Day: hours 11-21 (11 timesteps, all within 10:00-22:00 UTC)
        assert len(day_data["timesteps"]) == 11
        # Night: hours 22-23 (2 timesteps, within 22:00-10:00 UTC)
        assert len(night_data["timesteps"]) == 2

    def test_period_pop_is_max(self):
        """Period POP is the max of all timestep POPs."""
        store = _make_store()
        store.merge(TimestepData(time=_ts(12), pop=30))
        store.merge(TimestepData(time=_ts(13), pop=70))
        store.merge(TimestepData(time=_ts(14), pop=40))

        periods = [("2026-03-22", "day", _utc(10, 22), _utc(22, 22))]
        projection = store.project_periods(periods)

        assert projection[("2026-03-22", "day")]["pop"] == 70

    def test_period_rain_snow_sums(self):
        """Period rain/snow are sums of timestep values."""
        store = _make_store()
        store.merge(TimestepData(time=_ts(12), rain_mm=1.5))
        store.merge(TimestepData(time=_ts(13), rain_mm=2.0, snow_cm=0.5))
        store.merge(TimestepData(time=_ts(14), snow_cm=1.0))

        periods = [("2026-03-22", "day", _utc(10, 22), _utc(22, 22))]
        projection = store.project_periods(periods)

        day = projection[("2026-03-22", "day")]
        assert day["rain_mm"] == 3.5
        assert day["snow_cm"] == 1.5

    def test_empty_period_has_none_values(self):
        """Period with no timesteps has None pop/rain/snow and empty timesteps."""
        store = _make_store()
        periods = [("2026-03-22", "day", _utc(10, 22), _utc(22, 22))]
        projection = store.project_periods(periods)

        day = projection[("2026-03-22", "day")]
        assert day["pop"] is None
        assert day["rain_mm"] is None
        assert day["snow_cm"] is None
        assert day["timesteps"] == []

    def test_timesteps_sorted_by_time(self):
        """Timesteps in the projection are sorted chronologically."""
        store = _make_store()
        # Insert out of order
        store.merge(TimestepData(time=_ts(14), temp=-5.0))
        store.merge(TimestepData(time=_ts(12), temp=-3.0))
        store.merge(TimestepData(time=_ts(13), temp=-4.0))

        periods = [("2026-03-22", "day", _utc(10, 22), _utc(22, 22))]
        projection = store.project_periods(periods)

        timesteps = projection[("2026-03-22", "day")]["timesteps"]
        times = [ts["time"] for ts in timesteps]
        assert times == sorted(times)


# ---------------------------------------------------------------------------
# Hourly projection
# ---------------------------------------------------------------------------

class TestHourlyProjection:
    """Tests for projecting the store into hourly output format."""

    def test_hourly_output_format(self):
        """Hourly projection returns dict keyed by ISO timestamp."""
        store = _make_store()
        store.merge(TimestepData(
            time=_ts(12), temp=-3.0, rain_mm=1.5, snow_cm=0,
            pop=60, sky_state=5.0,
        ))

        hourly = store.project_hourly()

        assert _ts(12) in hourly
        entry = hourly[_ts(12)]
        assert entry["rain_mm"] == 1.5
        assert entry["snow_cm"] == 0
        assert entry["temp"] == -3.0
        assert entry["precipitation_probability"] == 60
        assert entry["sky_state"] == 5.0

    def test_hourly_includes_freezing_and_ice(self):
        """Hourly projection includes freezing_precip_mm and ice_pellet_cm."""
        store = _make_store()
        store.merge(TimestepData(
            time=_ts(12), freezing_precip_mm=2.5, ice_pellet_cm=0.3,
        ))

        hourly = store.project_hourly()
        entry = hourly[_ts(12)]
        assert entry["freezing_precip_mm"] == 2.5
        assert entry["ice_pellet_cm"] == 0.3

    def test_hourly_only_hrdps(self):
        """Hourly projection includes only HRDPS entries (1h resolution)."""
        store = _make_store()
        store.merge(TimestepData(time=_ts(12), temp=-3.0, model="hrdps"))
        store.merge(TimestepData(time=_ts(15), temp=-5.0, model="gdps"))

        hourly = store.project_hourly()

        assert _ts(12) in hourly
        assert _ts(15) not in hourly  # GDPS excluded from hourly


# ---------------------------------------------------------------------------
# Store utilities
# ---------------------------------------------------------------------------

class TestStoreUtilities:
    """Tests for store housekeeping methods."""

    def test_len(self):
        """len(store) returns number of entries."""
        store = _make_store()
        assert len(store) == 0
        store.merge(TimestepData(time=_ts(12)))
        assert len(store) == 1
        store.merge(TimestepData(time=_ts(13)))
        assert len(store) == 2

    def test_get_nonexistent_returns_none(self):
        """Getting a nonexistent key returns None."""
        store = _make_store()
        assert store.get("2026-03-22T12:00:00Z") is None

    def test_prune_old_entries(self):
        """prune_before() removes entries older than the cutoff."""
        store = _make_store()
        store.merge(TimestepData(time=_ts(10)))
        store.merge(TimestepData(time=_ts(12)))
        store.merge(TimestepData(time=_ts(14)))

        store.prune_before(_ts(12))

        assert store.get(_ts(10)) is None
        assert store.get(_ts(12)) is not None
        assert store.get(_ts(14)) is not None
        assert len(store) == 2


# ---------------------------------------------------------------------------
# Helper for UTC datetimes in period definitions
# ---------------------------------------------------------------------------

def _utc(hour: int, day: int = 22) -> datetime:
    """Build a UTC datetime for 2026-03-{day}T{hour}:00Z."""
    return datetime(2026, 3, day, hour, 0, tzinfo=timezone.utc)
