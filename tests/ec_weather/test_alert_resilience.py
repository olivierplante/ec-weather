"""Tests for alert last-known-good resilience through transient failures.

When an alerts refresh fails transiently but the coordinator already holds
good data, it must serve the retained alerts (pruned to their EC-declared
expirations) instead of dropping to unknown — the alert bar must never blank
during an active alert just because a single fetch cycle failed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from ec_weather.api_client import FetchError
from ec_weather.coordinator import ECAlertCoordinator
from ec_weather.coordinator.alerts import prune_retained_alerts

_BBOX = "44.420,-76.700,46.420,-74.700"
_FETCH = "ec_weather.coordinator.alerts.fetch_json_with_retry"


def _iso(dt: datetime) -> str:
    """UTC ISO string with the trailing Z the EC API uses."""
    return dt.isoformat().replace("+00:00", "Z")


def _response(
    expires: str,
    alert_type: str = "warning",
    headline: str = "Tornado Watch",
    text: str = "Conditions are favourable for tornadoes.",
) -> dict:
    """Build a minimal EC alerts API response with a single active alert."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "alert_type": alert_type,
                    "alert_name_en": headline,
                    "alert_text_en": text,
                    "status_en": "active",
                    "expiration_datetime": expires,
                },
            },
        ],
    }


def _retained(alerts: list[dict], highest_type: str | None) -> dict:
    """Build a retained (last-known-good) coordinator payload."""
    return {
        "alert_count": len(alerts),
        "alerts": alerts,
        "highest_type": highest_type,
    }


# ---------------------------------------------------------------------------
# Pure prune helper
# ---------------------------------------------------------------------------

class TestPruneRetainedAlerts:
    def test_expired_alert_pruned_unexpired_kept(self):
        """Given a mix of expired and future alerts → only future survive."""
        now = datetime.now(timezone.utc)
        past = _iso(now - timedelta(hours=1))
        future = _iso(now + timedelta(hours=3))
        retained = _retained(
            [
                {"headline": "Old Warning", "type": "warning",
                 "expires": past, "text": "gone"},
                {"headline": "Tornado Watch", "type": "watch",
                 "expires": future, "text": "still valid"},
            ],
            "warning",
        )

        pruned = prune_retained_alerts(retained)

        assert pruned["alert_count"] == 1
        assert pruned["alerts"][0]["headline"] == "Tornado Watch"
        # highest_type recomputed after the warning was pruned
        assert pruned["highest_type"] == "watch"
        assert pruned["stale"] is True

    def test_all_expired_yields_honest_empty(self):
        """Given every retained alert expired → empty state, not stale garbage."""
        now = datetime.now(timezone.utc)
        past = _iso(now - timedelta(minutes=1))
        retained = _retained(
            [{"headline": "Old", "type": "warning", "expires": past, "text": "t"}],
            "warning",
        )

        pruned = prune_retained_alerts(retained)

        assert pruned["alert_count"] == 0
        assert pruned["alerts"] == []
        assert pruned["highest_type"] is None
        assert pruned["stale"] is True


# ---------------------------------------------------------------------------
# Coordinator resilience
# ---------------------------------------------------------------------------

class TestCoordinatorResilience:
    async def test_transient_failure_serves_retained(self, hass: HomeAssistant):
        """Given prior data + transient fetch failure → retained alerts served."""
        future = _iso(datetime.now(timezone.utc) + timedelta(hours=3))
        coord = ECAlertCoordinator(hass, bbox=_BBOX, language="en")

        with patch(_FETCH, return_value=_response(future, "watch", "Tornado Watch")):
            await coord.async_refresh()
        assert coord.last_update_success is True
        assert coord.data["alert_count"] == 1

        with patch(_FETCH, side_effect=FetchError("connection reset")):
            await coord.async_refresh()

        # Stayed available with the retained alert intact.
        assert coord.last_update_success is True
        assert coord.data["alert_count"] == 1
        assert coord.data["alerts"][0]["headline"] == "Tornado Watch"
        assert coord.data["stale"] is True

    async def test_retained_prunes_expired_on_failure(self, hass: HomeAssistant):
        """Given a failure with a since-expired retained alert → it is pruned."""
        now = datetime.now(timezone.utc)
        past = _iso(now - timedelta(hours=1))
        future = _iso(now + timedelta(hours=3))
        coord = ECAlertCoordinator(hass, bbox=_BBOX, language="en")
        coord.data = _retained(
            [
                {"headline": "Old Warning", "type": "warning",
                 "expires": past, "text": "gone"},
                {"headline": "Tornado Watch", "type": "watch",
                 "expires": future, "text": "valid"},
            ],
            "warning",
        )
        coord._last_success_dt = now - timedelta(minutes=5)

        with patch(_FETCH, side_effect=FetchError("timeout")):
            await coord.async_refresh()

        assert coord.last_update_success is True
        assert coord.data["alert_count"] == 1
        assert coord.data["alerts"][0]["headline"] == "Tornado Watch"
        assert coord.data["highest_type"] == "watch"
        assert coord.data["stale"] is True

    async def test_first_fetch_failure_stays_unknown(self, hass: HomeAssistant):
        """Given no prior data + fetch failure → unknown (never fabricate)."""
        coord = ECAlertCoordinator(hass, bbox=_BBOX, language="en")
        assert coord.data is None

        with patch(_FETCH, side_effect=FetchError("dns failure")):
            await coord.async_refresh()

        assert coord.last_update_success is False
        assert coord.data is None

    async def test_first_fetch_failure_propagates_update_failed(
        self, hass: HomeAssistant
    ):
        """With nothing to retain, the FetchError propagates as UpdateFailed."""
        coord = ECAlertCoordinator(hass, bbox=_BBOX, language="en")
        with patch(_FETCH, side_effect=FetchError("dns failure")):
            with pytest.raises(UpdateFailed):
                await coord._async_update_data()

    async def test_success_replaces_retention_and_clears_stale(
        self, hass: HomeAssistant
    ):
        """A successful fetch replaces retained data entirely and clears stale."""
        now = datetime.now(timezone.utc)
        future = _iso(now + timedelta(hours=3))
        coord = ECAlertCoordinator(hass, bbox=_BBOX, language="en")
        # Seed a stale retained state as if a prior cycle had failed.
        coord.data = {
            "alert_count": 1,
            "alerts": [{"headline": "Old Watch", "type": "watch",
                        "expires": future, "text": "t"}],
            "highest_type": "watch",
            "stale": True,
        }
        coord._serving_retained = True

        with patch(_FETCH, return_value=_response(future, "warning", "Blizzard Warning")):
            await coord.async_refresh()

        assert coord.last_update_success is True
        assert "stale" not in coord.data
        assert coord.data["alert_count"] == 1
        assert coord.data["alerts"][0]["headline"] == "Blizzard Warning"
        assert coord.data["highest_type"] == "warning"
        assert coord._serving_retained is False

    async def test_binary_sensor_stays_on_through_blip(self, hass: HomeAssistant):
        """Binary sensor stays 'on' through a blip with an unexpired warning."""
        from ec_weather.binary_sensor import ECAlertActiveSensor

        future = _iso(datetime.now(timezone.utc) + timedelta(hours=3))
        coord = ECAlertCoordinator(hass, bbox=_BBOX, language="en")

        with patch(_FETCH, return_value=_response(future, "warning", "Blizzard Warning")):
            await coord.async_refresh()

        sensor = ECAlertActiveSensor(coord, "on-118", "Ottawa")
        assert sensor.is_on is True
        assert coord.last_update_success is True

        with patch(_FETCH, side_effect=FetchError("connection refused")):
            await coord.async_refresh()

        # The blip must not blank the alert — sensor remains on and available.
        assert coord.last_update_success is True
        assert sensor.is_on is True
