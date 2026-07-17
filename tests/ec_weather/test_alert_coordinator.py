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

def _feature(alert_type, headline, text, expires, status="active"):
    """Build a single EC alert feature for the merge-dedup tests."""
    return {
        "type": "Feature",
        "properties": {
            "alert_type": alert_type,
            "alert_name_en": headline,
            "alert_text_en": text,
            "status_en": status,
            "expiration_datetime": expires,
        },
    }


# ---------------------------------------------------------------------------
# Same-product merge — EC issues one copy per forecast sub-zone; the card
# shows no zones, so near-identical copies of the same (headline, type) are
# collapsed to the copy that stays valid longest.
# ---------------------------------------------------------------------------

class TestSameProductMerge:
    def test_latest_expiring_copy_kept_wholesale(self):
        """Same (headline, type), different text+expires → latest copy survives whole."""
        data = {
            "type": "FeatureCollection",
            "features": [
                _feature(
                    "warning", "Air Quality Warning",
                    "Quebec-zone wording.", "2099-01-01T00:00:00Z",
                ),
                _feature(
                    "warning", "Air Quality Warning",
                    "Ottawa-zone wording.", "2099-06-01T00:00:00Z",
                ),
            ],
        }
        result = parse_alert_response(data)

        assert result["alert_count"] == 1
        survivor = result["alerts"][0]
        # Latest expires wins, and its text travels with it (no field mixing).
        assert survivor["expires"] == "2099-06-01T00:00:00Z"
        assert survivor["text"] == "Ottawa-zone wording."

    def test_tie_on_expires_keeps_first_occurrence(self):
        """Equal expires → first occurrence survives."""
        data = {
            "type": "FeatureCollection",
            "features": [
                _feature(
                    "warning", "Heat Warning",
                    "First copy.", "2099-01-01T00:00:00Z",
                ),
                _feature(
                    "warning", "Heat Warning",
                    "Second copy.", "2099-01-01T00:00:00Z",
                ),
            ],
        }
        result = parse_alert_response(data)

        assert result["alert_count"] == 1
        assert result["alerts"][0]["text"] == "First copy."

    def test_invalid_expires_loses_to_valid(self):
        """A copy with unparseable/missing expires loses to a valid-expires copy."""
        data = {
            "type": "FeatureCollection",
            "features": [
                _feature(
                    "warning", "Snowfall Warning",
                    "No-expiry copy.", None,
                ),
                _feature(
                    "warning", "Snowfall Warning",
                    "Valid-expiry copy.", "2099-01-01T00:00:00Z",
                ),
                _feature(
                    "warning", "Snowfall Warning",
                    "Garbage-expiry copy.", "not-a-date",
                ),
            ],
        }
        result = parse_alert_response(data)

        assert result["alert_count"] == 1
        assert result["alerts"][0]["text"] == "Valid-expiry copy."

    def test_all_invalid_expires_keeps_first_occurrence(self):
        """If no copy of a key has a valid expires → first occurrence survives."""
        data = {
            "type": "FeatureCollection",
            "features": [
                _feature(
                    "warning", "Fog Advisory",
                    "First bad-expiry copy.", "not-a-date",
                ),
                _feature(
                    "warning", "Fog Advisory",
                    "Second bad-expiry copy.", None,
                ),
            ],
        }
        result = parse_alert_response(data)

        assert result["alert_count"] == 1
        assert result["alerts"][0]["text"] == "First bad-expiry copy."

    def test_same_headline_different_type_not_merged(self):
        """Same headline but different type → kept as two distinct alerts."""
        data = {
            "type": "FeatureCollection",
            "features": [
                _feature(
                    "warning", "Winter Storm",
                    "Warning text.", "2099-01-01T00:00:00Z",
                ),
                _feature(
                    "watch", "Winter Storm",
                    "Watch text.", "2099-01-01T00:00:00Z",
                ),
            ],
        }
        result = parse_alert_response(data)

        assert result["alert_count"] == 2

    def test_severe_thunderstorm_warning_and_watch_stay_two(self):
        """Realistic warning-vs-watch (different headlines) stays two alerts."""
        data = {
            "type": "FeatureCollection",
            "features": [
                _feature(
                    "warning", "Severe Thunderstorm Warning",
                    "Damaging winds now.", "2099-01-01T00:00:00Z",
                ),
                _feature(
                    "watch", "Severe Thunderstorm Watch",
                    "Conditions favourable.", "2099-01-01T00:00:00Z",
                ),
            ],
        }
        result = parse_alert_response(data)

        assert result["alert_count"] == 2

    def test_count_and_highest_type_over_merged_list(self):
        """alert_count and highest_type are computed after the merge."""
        data = {
            "type": "FeatureCollection",
            "features": [
                _feature(
                    "advisory", "Wind Advisory",
                    "Advisory copy A.", "2099-01-01T00:00:00Z",
                ),
                _feature(
                    "advisory", "Wind Advisory",
                    "Advisory copy B.", "2099-06-01T00:00:00Z",
                ),
                _feature(
                    "warning", "Heat Warning",
                    "Heat warning.", "2099-01-01T00:00:00Z",
                ),
            ],
        }
        result = parse_alert_response(data)

        assert result["alert_count"] == 2
        assert result["highest_type"] == "warning"

    def test_order_stable_by_first_occurrence(self):
        """Merged list preserves first-occurrence order of each key."""
        data = {
            "type": "FeatureCollection",
            "features": [
                _feature(
                    "warning", "Alpha Warning",
                    "Alpha copy 1.", "2099-01-01T00:00:00Z",
                ),
                _feature(
                    "warning", "Beta Warning",
                    "Beta copy.", "2099-01-01T00:00:00Z",
                ),
                _feature(
                    "warning", "Alpha Warning",
                    "Alpha copy 2 later.", "2099-06-01T00:00:00Z",
                ),
            ],
        }
        result = parse_alert_response(data)

        headlines = [a["headline"] for a in result["alerts"]]
        assert headlines == ["Alpha Warning", "Beta Warning"]
        # Alpha kept its later-expiring copy but its first-seen position.
        assert result["alerts"][0]["text"] == "Alpha copy 2 later."

    def test_air_quality_regression(self):
        """Today's finding: 3 air-quality-warning copies + 1 heat warning → 2 alerts."""
        data = {
            "type": "FeatureCollection",
            "features": [
                _feature(
                    "warning", "Air Quality Warning",
                    "Poor air quality across the Quebec zone.",
                    "2099-01-01T00:00:00Z",
                ),
                _feature(
                    "warning", "Air Quality Warning",
                    "Poor air quality across the Ottawa zone.",
                    "2099-06-01T00:00:00Z",
                ),
                _feature(
                    "warning", "Air Quality Warning",
                    "Poor air quality across the Gatineau zone.",
                    "2099-03-01T00:00:00Z",
                ),
                _feature(
                    "warning", "Heat Warning",
                    "High temperatures expected.", "2099-01-01T00:00:00Z",
                ),
            ],
        }
        result = parse_alert_response(data)

        assert result["alert_count"] == 2
        headlines = [a["headline"] for a in result["alerts"]]
        assert headlines == ["Air Quality Warning", "Heat Warning"]
        air = result["alerts"][0]
        assert air["expires"] == "2099-06-01T00:00:00Z"
        assert air["text"] == "Poor air quality across the Ottawa zone."


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
