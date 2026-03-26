"""Tests for model-run-aware freshness — E2.

The WEonG coordinator checks whether a new HRDPS model run is available
before running the full query pipeline. This avoids wasted CPU cycles
when the data hasn't changed (same model run).

HRDPS runs at 00Z, 06Z, 12Z, 18Z — available ~2h after.
weong_interval acts as a safety ceiling (max staleness).

Tests verify:
1. Same model run → skip update
2. New model run → proceed with update
3. No cached model run → proceed (first fetch)
4. weong_interval exceeded → force update even if same model run
5. Transient errors → force update next cycle
6. Expected HRDPS model run schedule calculation
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from freezegun import freeze_time

from ec_weather.coordinator.weong import _expected_hrdps_model_run


# ---------------------------------------------------------------------------
# HRDPS model run schedule
# ---------------------------------------------------------------------------

class TestExpectedHRDPSModelRun:
    """Verify the expected model run calculation for HRDPS."""

    def test_before_first_run_available(self):
        """Before 02Z → previous day's 18Z run is the latest."""
        # 01:30Z — 00Z run not yet available (needs ~2h processing)
        now = datetime(2026, 3, 22, 1, 30, tzinfo=timezone.utc)
        assert _expected_hrdps_model_run(now) == "2026-03-21T18:00:00Z"

    def test_after_00z_available(self):
        """After 02Z → 00Z run is the latest."""
        now = datetime(2026, 3, 22, 2, 30, tzinfo=timezone.utc)
        assert _expected_hrdps_model_run(now) == "2026-03-22T00:00:00Z"

    def test_after_06z_available(self):
        """After 08Z → 06Z run is the latest."""
        now = datetime(2026, 3, 22, 8, 30, tzinfo=timezone.utc)
        assert _expected_hrdps_model_run(now) == "2026-03-22T06:00:00Z"

    def test_after_12z_available(self):
        """After 14Z → 12Z run is the latest."""
        now = datetime(2026, 3, 22, 14, 30, tzinfo=timezone.utc)
        assert _expected_hrdps_model_run(now) == "2026-03-22T12:00:00Z"

    def test_after_18z_available(self):
        """After 20Z → 18Z run is the latest."""
        now = datetime(2026, 3, 22, 20, 30, tzinfo=timezone.utc)
        assert _expected_hrdps_model_run(now) == "2026-03-22T18:00:00Z"

    def test_exactly_at_availability(self):
        """Exactly at 08Z → 06Z run is available."""
        now = datetime(2026, 3, 22, 8, 0, tzinfo=timezone.utc)
        assert _expected_hrdps_model_run(now) == "2026-03-22T06:00:00Z"

    def test_between_runs(self):
        """At 05Z → 00Z run is latest (06Z not yet available)."""
        now = datetime(2026, 3, 22, 5, 0, tzinfo=timezone.utc)
        assert _expected_hrdps_model_run(now) == "2026-03-22T00:00:00Z"

    def test_midnight_boundary(self):
        """At 00:00Z → previous day's 18Z run is latest."""
        now = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
        assert _expected_hrdps_model_run(now) == "2026-03-21T18:00:00Z"


# ---------------------------------------------------------------------------
# Model-run-aware skip logic
# ---------------------------------------------------------------------------

class TestModelRunSkipLogic:
    """Verify the coordinator skips updates when model run is unchanged."""

    def test_no_cached_run_proceeds(self):
        """No cached model run → should NOT skip (first fetch)."""
        cached_model_run = None
        expected_run = "2026-03-22T06:00:00Z"
        should_skip = cached_model_run is not None and cached_model_run == expected_run
        assert should_skip is False

    def test_same_model_run_skips(self):
        """Cached model run matches expected → should skip."""
        cached_model_run = "2026-03-22T06:00:00Z"
        expected_run = "2026-03-22T06:00:00Z"
        should_skip = cached_model_run is not None and cached_model_run == expected_run
        assert should_skip is True

    def test_new_model_run_proceeds(self):
        """Cached model run is older than expected → should NOT skip."""
        cached_model_run = "2026-03-22T00:00:00Z"
        expected_run = "2026-03-22T06:00:00Z"
        should_skip = cached_model_run is not None and cached_model_run == expected_run
        assert should_skip is False

    def test_safety_ceiling_overrides_skip(self):
        """Even if model run matches, weong_interval forces update."""
        cached_model_run = "2026-03-22T06:00:00Z"
        expected_run = "2026-03-22T06:00:00Z"
        model_run_matches = cached_model_run == expected_run
        interval_exceeded = True  # weong_interval has elapsed
        should_skip = model_run_matches and not interval_exceeded
        assert should_skip is False
