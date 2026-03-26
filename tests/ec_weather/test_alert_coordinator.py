"""Tests for alert parsing — pure function tests on parse_alert_response."""

from __future__ import annotations

from ec_weather.coordinator.alerts import parse_alert_response

from .conftest import load_fixture


# ---------------------------------------------------------------------------
# No alerts
# ---------------------------------------------------------------------------

class TestNoAlerts:
    def test_empty_features(self):
        """Given empty features array → no alerts."""
        data = load_fixture("weather_alerts_empty.json")
        result = parse_alert_response(data)

        assert result["alert_count"] == 0
        assert result["alerts"] == []
        assert result["highest_type"] is None


# ---------------------------------------------------------------------------
# Alert parsing
# ---------------------------------------------------------------------------

class TestAlertParsing:
    def test_active_warning(self):
        """Given warning alert → correct headline, type, text parsed."""
        data = load_fixture("weather_alerts_active.json")
        result = parse_alert_response(data)

        assert result["alert_count"] >= 1

        warnings = [a for a in result["alerts"] if a["type"] == "warning"]
        assert len(warnings) >= 1
        assert warnings[0]["headline"] == "Blizzard Warning"
        assert "Heavy snow" in warnings[0]["text"]

    def test_highest_type_is_warning(self):
        """Given warning + advisory → highest_type = warning."""
        data = load_fixture("weather_alerts_active.json")
        result = parse_alert_response(data)

        assert result["highest_type"] == "warning"


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

class TestAlertFiltering:
    def test_expired_alert_excluded(self):
        """Given alert with past expiry → not included."""
        data = load_fixture("weather_alerts_active.json")
        result = parse_alert_response(data)

        headlines = [a["headline"] for a in result["alerts"]]
        assert "Freezing Rain Watch" not in headlines

    def test_cancelled_alert_excluded(self):
        """Given cancelled status → not included."""
        data = load_fixture("weather_alerts_active.json")
        result = parse_alert_response(data)

        headlines = [a["headline"] for a in result["alerts"]]
        assert "Special Weather Statement" not in headlines

    def test_empty_text_alert_excluded(self):
        """Given alert with empty text → not included."""
        data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "alert_type": "warning",
                        "alert_name_en": "Real Warning",
                        "alert_text_en": "Actual warning text with content",
                        "status_en": "active",
                        "expiration_datetime": "2099-12-31T23:59:59Z",
                    },
                },
                {
                    "type": "Feature",
                    "properties": {
                        "alert_type": "statement",
                        "alert_name_en": "Empty Statement",
                        "alert_text_en": "",
                        "status_en": "active",
                        "expiration_datetime": "2099-12-31T23:59:59Z",
                    },
                },
                {
                    "type": "Feature",
                    "properties": {
                        "alert_type": "statement",
                        "alert_name_en": "Whitespace Statement",
                        "alert_text_en": "   ",
                        "status_en": "active",
                        "expiration_datetime": "2099-12-31T23:59:59Z",
                    },
                },
            ],
        }
        result = parse_alert_response(data)

        assert result["alert_count"] == 1
        assert result["alerts"][0]["headline"] == "Real Warning"

    def test_duplicate_alerts_deduplicated(self):
        """Given duplicate alerts (same headline+text) → deduplicated."""
        data = load_fixture("weather_alerts_active.json")
        result = parse_alert_response(data)

        blizzards = [a for a in result["alerts"] if a["headline"] == "Blizzard Warning"]
        assert len(blizzards) == 1


# ---------------------------------------------------------------------------
# Priority
# ---------------------------------------------------------------------------

class TestAlertPriority:
    def test_priority_order(self):
        """Given multiple alert types → highest_type reflects priority."""
        data = {
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
        result = parse_alert_response(data)

        assert result["highest_type"] == "watch"


# ---------------------------------------------------------------------------
# Language support
# ---------------------------------------------------------------------------

class TestAlertLanguage:
    def test_french_headline(self):
        """Given French language → uses French headline."""
        data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "alert_type": "warning",
                        "alert_name_en": "Blizzard Warning",
                        "alert_name_fr": "Avertissement de blizzard",
                        "alert_text_en": "Heavy snow expected",
                        "alert_text_fr": "Forte neige prévue",
                        "status_en": "active",
                        "expiration_datetime": "2099-12-31T23:59:59Z",
                    },
                },
            ],
        }
        result = parse_alert_response(data, language="fr")

        assert result["alerts"][0]["headline"] == "Avertissement de blizzard"
        assert result["alerts"][0]["text"] == "Forte neige prévue"
