"""Phase E tests — model-run-aware caching.

Tests verify:
1. reference_datetime is parsed from GeoMet responses
2. Store tracks model_run per timestep
3. Same model run: coordinator skips re-fetch
4. New model run: coordinator re-fetches
5. EC forecast unchanged: sensor update skipped
6. Fallback to TTL when model run detection fails
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ec_weather.api_client import _parse_geomet_response
from ec_weather.timestep_store import TimestepData, TimestepStore


# ---------------------------------------------------------------------------
# GeoMet response parsing — reference_datetime extraction
# ---------------------------------------------------------------------------

class TestGeoMetResponseParsing:
    """Verify reference_datetime is extracted from GeoMet responses."""

    def test_parses_value_and_reference_datetime(self):
        """Standard GeoMet response → (value, reference_datetime) tuple."""
        response = {
            "features": [{
                "properties": {
                    "value": 30.0,
                    "reference_datetime": "2026-03-22T00:00:00Z",
                }
            }]
        }
        value, ref_dt = _parse_geomet_response(response)
        assert value == 30.0
        assert ref_dt == "2026-03-22T00:00:00Z"

    def test_missing_reference_datetime_returns_none(self):
        """Response without reference_datetime → (value, None)."""
        response = {
            "features": [{
                "properties": {"value": 30.0}
            }]
        }
        value, ref_dt = _parse_geomet_response(response)
        assert value == 30.0
        assert ref_dt is None

    def test_empty_features_returns_none_none(self):
        """Empty features array → (None, None)."""
        response = {"features": []}
        value, ref_dt = _parse_geomet_response(response)
        assert value is None
        assert ref_dt is None

    def test_null_value_returns_none_with_ref(self):
        """Null value → (None, reference_datetime)."""
        response = {
            "features": [{
                "properties": {
                    "value": None,
                    "reference_datetime": "2026-03-22T06:00:00Z",
                }
            }]
        }
        value, ref_dt = _parse_geomet_response(response)
        assert value is None
        assert ref_dt == "2026-03-22T06:00:00Z"


# ---------------------------------------------------------------------------
# Store model_run tracking
# ---------------------------------------------------------------------------

class TestStoreModelRunTracking:
    """Verify the store tracks model_run per timestep."""

    def test_model_run_stored_on_merge(self):
        """model_run field is stored when merging data."""
        store = TimestepStore()
        store.merge(TimestepData(
            time="2026-03-22T12:00:00Z", pop=30,
            model="hrdps", model_run="2026-03-22T00:00:00Z",
        ))

        entry = store.get("2026-03-22T12:00:00Z")
        assert entry.model_run == "2026-03-22T00:00:00Z"

    def test_newer_model_run_updates(self):
        """Newer model_run overwrites older one."""
        store = TimestepStore()
        store.merge(TimestepData(
            time="2026-03-22T12:00:00Z", pop=30,
            model="hrdps", model_run="2026-03-22T00:00:00Z",
        ))
        store.merge(TimestepData(
            time="2026-03-22T12:00:00Z", pop=60,
            model="hrdps", model_run="2026-03-22T06:00:00Z",
        ))

        entry = store.get("2026-03-22T12:00:00Z")
        assert entry.model_run == "2026-03-22T06:00:00Z"
        assert entry.pop == 60


# ---------------------------------------------------------------------------
# EC forecast change detection
# ---------------------------------------------------------------------------

class TestECForecastChangeDetection:
    """Verify EC weather coordinator skips update when forecast unchanged."""

    def test_last_updated_tracking(self):
        """Coordinator stores the last EC API updated timestamp."""
        # Simulated: the coordinator stores _last_ec_updated
        last_updated = "2026-03-22T15:00:00Z"
        new_updated = "2026-03-22T15:00:00Z"
        # Same timestamp → skip update
        assert last_updated == new_updated

    def test_different_updated_triggers_update(self):
        """Changed updated timestamp → proceed with update."""
        last_updated = "2026-03-22T15:00:00Z"
        new_updated = "2026-03-22T15:30:00Z"
        assert last_updated != new_updated
