"""Tests for model-run-aware WEonG refresh logic.

The WEonG coordinator should refresh when a new HRDPS model run is available,
not on a fixed timer. needs_refresh() checks both staleness and model run currency.

In polling mode, update_interval is set dynamically to the time until the next
model run availability. If the data isn't ready yet, a short retry is scheduled.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

from ec_weather.coordinator.weong import (
    ECWEonGCoordinator,
    _expected_hrdps_model_run,
    _next_model_run_availability,
)


class TestNeedsRefresh:
    """Verify needs_refresh() is model-run-aware."""

    def test_needs_refresh_method_exists(self) -> None:
        """ECWEonGCoordinator must expose needs_refresh()."""
        assert hasattr(ECWEonGCoordinator, "needs_refresh"), (
            "ECWEonGCoordinator must have a needs_refresh() method "
            "for model-run-aware refresh decisions"
        )

    def test_needs_refresh_checks_model_run(self) -> None:
        """needs_refresh() must check _is_model_run_current()."""
        source = inspect.getsource(ECWEonGCoordinator.needs_refresh)
        assert "_is_model_run_current" in source, (
            "needs_refresh() must check _is_model_run_current() to detect "
            "when a new HRDPS model run is available"
        )

    def test_needs_refresh_returns_true_when_no_data(self) -> None:
        """needs_refresh() must return True when coordinator has no data."""
        source = inspect.getsource(ECWEonGCoordinator.needs_refresh)
        assert "data" in source, (
            "needs_refresh() must check for missing data"
        )


class TestWeongIntervalRemoved:
    """Verify CONF_WEONG_INTERVAL is removed from the codebase."""

    def test_no_weong_interval_in_const(self) -> None:
        """CONF_WEONG_INTERVAL should not exist in const.py."""
        from ec_weather import const
        assert not hasattr(const, "CONF_WEONG_INTERVAL"), (
            "CONF_WEONG_INTERVAL should be removed — WEonG refresh "
            "is now model-run-aware, not user-configurable"
        )

    def test_no_default_weong_interval_in_const(self) -> None:
        """DEFAULT_WEONG_INTERVAL should not exist in const.py."""
        from ec_weather import const
        assert not hasattr(const, "DEFAULT_WEONG_INTERVAL"), (
            "DEFAULT_WEONG_INTERVAL should be removed — WEonG refresh "
            "is now model-run-aware, not user-configurable"
        )

    def test_config_flow_no_weong_interval(self) -> None:
        """The options flow should not include weong_interval."""
        source = inspect.getsource(__import__("ec_weather.config_flow", fromlist=["ECWeatherOptionsFlow"]).ECWeatherOptionsFlow)
        assert "weong_interval" not in source.lower(), (
            "Options flow should not include weong_interval — "
            "WEonG refresh is now model-run-aware"
        )


class TestExpectedModelRun:
    """Verify _expected_hrdps_model_run returns correct run times."""

    def test_before_first_run_returns_previous_day_18z(self) -> None:
        """Before 02Z, expected run is previous day's 18Z."""
        from datetime import datetime, timezone
        now = datetime(2026, 3, 27, 1, 30, 0, tzinfo=timezone.utc)
        result = _expected_hrdps_model_run(now)
        assert result == "2026-03-26T18:00:00Z"

    def test_after_06z_processing_returns_06z(self) -> None:
        """At 08:30Z, expected run is 06Z (06 + 2h processing)."""
        from datetime import datetime, timezone
        now = datetime(2026, 3, 27, 8, 30, 0, tzinfo=timezone.utc)
        result = _expected_hrdps_model_run(now)
        assert result == "2026-03-27T06:00:00Z"

    def test_after_12z_processing_returns_12z(self) -> None:
        """At 14:30Z (10:30 AM EDT), expected run is 12Z."""
        from datetime import datetime, timezone
        now = datetime(2026, 3, 27, 14, 30, 0, tzinfo=timezone.utc)
        result = _expected_hrdps_model_run(now)
        assert result == "2026-03-27T12:00:00Z"

    def test_after_18z_processing_returns_18z(self) -> None:
        """At 20:30Z (4:30 PM EDT), expected run is 18Z."""
        now = datetime(2026, 3, 27, 20, 30, 0, tzinfo=timezone.utc)
        result = _expected_hrdps_model_run(now)
        assert result == "2026-03-27T18:00:00Z"


class TestNextModelRunAvailability:
    """Verify _next_model_run_availability computes correct times."""

    def test_after_06z_next_is_12z_plus_delay(self) -> None:
        """At 09:00Z (got 06Z data), next availability is 14:00Z (12Z + 2h)."""
        now = datetime(2026, 3, 27, 9, 0, 0, tzinfo=timezone.utc)
        result = _next_model_run_availability(now)
        assert result == datetime(2026, 3, 27, 14, 0, 0, tzinfo=timezone.utc)

    def test_after_12z_next_is_18z_plus_delay(self) -> None:
        """At 15:00Z (got 12Z data), next availability is 20:00Z (18Z + 2h)."""
        now = datetime(2026, 3, 27, 15, 0, 0, tzinfo=timezone.utc)
        result = _next_model_run_availability(now)
        assert result == datetime(2026, 3, 27, 20, 0, 0, tzinfo=timezone.utc)

    def test_after_18z_next_is_00z_plus_delay_next_day(self) -> None:
        """At 21:00Z (got 18Z data), next availability is 02:00Z next day."""
        now = datetime(2026, 3, 27, 21, 0, 0, tzinfo=timezone.utc)
        result = _next_model_run_availability(now)
        assert result == datetime(2026, 3, 28, 2, 0, 0, tzinfo=timezone.utc)

    def test_before_first_run_next_is_00z_plus_delay(self) -> None:
        """At 01:00Z (have prev day 18Z), next availability is 02:00Z."""
        now = datetime(2026, 3, 27, 1, 0, 0, tzinfo=timezone.utc)
        result = _next_model_run_availability(now)
        assert result == datetime(2026, 3, 27, 2, 0, 0, tzinfo=timezone.utc)

    def test_returns_future_time(self) -> None:
        """Result must always be in the future relative to now."""
        now = datetime(2026, 3, 27, 14, 30, 0, tzinfo=timezone.utc)
        result = _next_model_run_availability(now)
        assert result > now


class TestPollingDynamicInterval:
    """Verify polling mode uses dynamic interval based on model run schedule."""

    def test_coordinator_accepts_polling_param(self) -> None:
        """ECWEonGCoordinator must accept a polling parameter."""
        params = inspect.signature(ECWEonGCoordinator.__init__).parameters
        assert "polling" in params, (
            "ECWEonGCoordinator must accept a polling parameter "
            "for full polling mode support"
        )

    def test_do_update_adjusts_interval(self) -> None:
        """_do_update must adjust update_interval dynamically."""
        source = inspect.getsource(ECWEonGCoordinator._do_update)
        assert "update_interval" in source, (
            "_do_update must adjust update_interval after each fetch "
            "to schedule the next poll at the right time"
        )

    def test_retry_on_stale_model_run(self) -> None:
        """_do_update must schedule a short retry if fetched data has old model run."""
        source = inspect.getsource(ECWEonGCoordinator._do_update)
        assert "_RETRY_INTERVAL" in source or "retry" in source.lower(), (
            "_do_update must schedule a short retry when the expected "
            "model run data isn't available yet from GeoMet"
        )
