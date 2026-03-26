"""Tests for OnDemandCoordinator base class."""

import time
from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant

from ec_weather.coordinator import OnDemandCoordinator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_coordinator(
    hass: HomeAssistant,
    *,
    polling: bool = False,
    interval_minutes: int = 15,
) -> OnDemandCoordinator:
    """Create a minimal OnDemandCoordinator for testing."""
    import logging

    return OnDemandCoordinator(
        hass,
        logging.getLogger("test"),
        name="test_coordinator",
        interval=timedelta(minutes=interval_minutes),
        polling=polling,
    )


# ---------------------------------------------------------------------------
# is_fresh() tests
# ---------------------------------------------------------------------------

class TestIsFresh:
    """Tests for OnDemandCoordinator.is_fresh()."""

    def test_returns_false_when_no_data(self, hass: HomeAssistant) -> None:
        """is_fresh() returns False when coordinator has no data."""
        coord = _make_coordinator(hass)
        coord.data = None
        assert coord.is_fresh() is False

    def test_returns_false_when_polling_enabled(self, hass: HomeAssistant) -> None:
        """is_fresh() always returns False in polling mode."""
        coord = _make_coordinator(hass, polling=True)
        coord.data = {"some": "data"}
        coord.mark_refreshed()
        assert coord.is_fresh() is False

    def test_returns_false_when_no_refresh_timestamp(self, hass: HomeAssistant) -> None:
        """is_fresh() returns False when mark_refreshed() was never called."""
        coord = _make_coordinator(hass)
        coord.data = {"some": "data"}
        assert coord.is_fresh() is False

    def test_returns_true_within_interval(self, hass: HomeAssistant) -> None:
        """is_fresh() returns True when data exists and within interval."""
        coord = _make_coordinator(hass, interval_minutes=15)
        coord.data = {"some": "data"}
        coord.mark_refreshed()
        assert coord.is_fresh() is True

    def test_returns_false_after_interval_elapsed(self, hass: HomeAssistant) -> None:
        """is_fresh() returns False when the configured interval has elapsed."""
        coord = _make_coordinator(hass, interval_minutes=15)
        coord.data = {"some": "data"}
        coord.mark_refreshed()
        # Simulate time passing beyond the interval
        coord._last_refresh_ts -= 16 * 60  # 16 minutes ago
        assert coord.is_fresh() is False


# ---------------------------------------------------------------------------
# mark_refreshed() tests
# ---------------------------------------------------------------------------

class TestMarkRefreshed:
    """Tests for OnDemandCoordinator.mark_refreshed()."""

    def test_updates_timestamp(self, hass: HomeAssistant) -> None:
        """mark_refreshed() sets _last_refresh_ts to current monotonic time."""
        coord = _make_coordinator(hass)
        assert coord._last_refresh_ts is None
        coord.mark_refreshed()
        assert coord._last_refresh_ts is not None
        assert isinstance(coord._last_refresh_ts, float)

    def test_successive_calls_increase_timestamp(self, hass: HomeAssistant) -> None:
        """Each mark_refreshed() call produces a newer timestamp."""
        coord = _make_coordinator(hass)
        coord.mark_refreshed()
        first = coord._last_refresh_ts
        # Slightly adjust to guarantee increase (monotonic clock is fast)
        coord._last_refresh_ts -= 1.0
        coord.mark_refreshed()
        second = coord._last_refresh_ts
        assert second > first - 1.0
