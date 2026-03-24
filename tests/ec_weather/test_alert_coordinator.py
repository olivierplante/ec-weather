"""Tests for ECAlertCoordinator — alert parsing, filtering, and deduplication."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant

from ec_weather.coordinator import ECAlertCoordinator

from .conftest import load_fixture


def _make_coordinator(hass: HomeAssistant) -> ECAlertCoordinator:
    return ECAlertCoordinator(
        hass, bbox="44.420,-76.700,46.420,-74.700", language="en"
    )


ALERTS_URL = (
    "https://api.weather.gc.ca/collections/weather-alerts/items"
    "?bbox=44.420,-76.700,46.420,-74.700&f=json&skipGeometry=true"
)


class TestNoAlerts:
    async def test_empty_features(self, hass: HomeAssistant, aioclient_mock):
        """Given empty features array → no alerts."""
        aioclient_mock.get(ALERTS_URL, json=load_fixture("weather_alerts_empty.json"))

        coord = _make_coordinator(hass)
        result = await coord._async_update_data()

        assert result["alert_count"] == 0
        assert result["alerts"] == []
        assert result["highest_type"] is None


class TestAlertParsing:
    async def test_active_warning(self, hass: HomeAssistant, aioclient_mock):
        """Given warning alert → correct headline, type, text parsed."""
        aioclient_mock.get(ALERTS_URL, json=load_fixture("weather_alerts_active.json"))

        coord = _make_coordinator(hass)
        result = await coord._async_update_data()

        # Should have active alerts (fixture has warning + advisory, minus cancelled and expired)
        assert result["alert_count"] >= 1

        # Find the blizzard warning
        warnings = [a for a in result["alerts"] if a["type"] == "warning"]
        assert len(warnings) >= 1
        assert warnings[0]["headline"] == "Blizzard Warning"
        assert "Heavy snow" in warnings[0]["text"]

    async def test_highest_type_is_warning(self, hass: HomeAssistant, aioclient_mock):
        """Given warning + advisory → highest_type = warning."""
        aioclient_mock.get(ALERTS_URL, json=load_fixture("weather_alerts_active.json"))

        coord = _make_coordinator(hass)
        result = await coord._async_update_data()

        assert result["highest_type"] == "warning"


class TestAlertFiltering:
    async def test_expired_alert_excluded(self, hass: HomeAssistant, aioclient_mock):
        """Given alert with past expiry → not included."""
        aioclient_mock.get(ALERTS_URL, json=load_fixture("weather_alerts_active.json"))

        coord = _make_coordinator(hass)
        result = await coord._async_update_data()

        # The fixture has a "Freezing Rain Watch" with expiry in 2020 — should be excluded
        headlines = [a["headline"] for a in result["alerts"]]
        assert "Freezing Rain Watch" not in headlines

    async def test_cancelled_alert_excluded(self, hass: HomeAssistant, aioclient_mock):
        """Given cancelled status → not included."""
        aioclient_mock.get(ALERTS_URL, json=load_fixture("weather_alerts_active.json"))

        coord = _make_coordinator(hass)
        result = await coord._async_update_data()

        # The fixture has a "Special Weather Statement" with status=cancelled
        headlines = [a["headline"] for a in result["alerts"]]
        assert "Special Weather Statement" not in headlines

    async def test_duplicate_alerts_deduplicated(self, hass: HomeAssistant, aioclient_mock):
        """Given duplicate alerts (same headline+text) → deduplicated."""
        aioclient_mock.get(ALERTS_URL, json=load_fixture("weather_alerts_active.json"))

        coord = _make_coordinator(hass)
        result = await coord._async_update_data()

        # Fixture has 2 identical "Blizzard Warning" entries (simulating sub-zones)
        blizzards = [a for a in result["alerts"] if a["headline"] == "Blizzard Warning"]
        assert len(blizzards) == 1  # deduplicated to 1


class TestAlertPriority:
    async def test_priority_order(self, hass: HomeAssistant, aioclient_mock):
        """Given multiple alert types → highest_type reflects priority."""
        # Build a fixture with watch + advisory (no warning)
        fixture = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "alert_type": "advisory",
                        "alert_name_en": "Test Advisory",
                        "alert_text_en": "Advisory text",
                        "status_en": "active",
                        "expiration_datetime": "2099-12-31T23:59:59Z",
                    },
                },
                {
                    "type": "Feature",
                    "properties": {
                        "alert_type": "watch",
                        "alert_name_en": "Test Watch",
                        "alert_text_en": "Watch text",
                        "status_en": "active",
                        "expiration_datetime": "2099-12-31T23:59:59Z",
                    },
                },
                {
                    "type": "Feature",
                    "properties": {
                        "alert_type": "statement",
                        "alert_name_en": "Test Statement",
                        "alert_text_en": "Statement text",
                        "status_en": "active",
                        "expiration_datetime": "2099-12-31T23:59:59Z",
                    },
                },
            ],
        }
        aioclient_mock.get(ALERTS_URL, json=fixture)

        coord = _make_coordinator(hass)
        result = await coord._async_update_data()

        # watch > advisory > statement
        assert result["highest_type"] == "watch"
