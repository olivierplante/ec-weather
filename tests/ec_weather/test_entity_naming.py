"""Tests that entity naming lives in the translation files (Phase 1).

Every entity drops the hardcoded ``_attr_name`` and exposes an
``_attr_translation_key`` equal to its strings.json key, so names come from
strings.json / translations/*.json (and French names are provided). This
decouples naming from the card contract (discovery resolves by unique_id) and
gives localized entity names.

The parity test is the drift guard: every translation_key used in the source
must have an entry under the right domain in all three translation files, and
the three files must carry identical entity-section key sets.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from homeassistant.helpers.typing import UNDEFINED

import ec_weather
from ec_weather.binary_sensor import ECAlertActiveSensor
from ec_weather.sensor import (
    CURRENT_SENSOR_DESCRIPTIONS,
    GAUGE_SENSOR_DESCRIPTIONS,
    ECAlertCountSensor,
    ECAlertsSensor,
    ECAQHISensor,
    ECDailyForecastSensor,
    ECHourlyForecastSensor,
    ECTodayPopSensor,
    ECWeatherSummarySensor,
    ECYesterdayPrecipSensor,
    yesterday_precip_sensor_keys,
)
from ec_weather.weather import ECWeather

COMPONENT_DIR = Path(ec_weather.__file__).parent
STRINGS_FILE = COMPONENT_DIR / "strings.json"
EN_FILE = COMPONENT_DIR / "translations" / "en.json"
FR_FILE = COMPONENT_DIR / "translations" / "fr.json"
TRANSLATION_FILES = {"strings.json": STRINGS_FILE, "en.json": EN_FILE, "fr.json": FR_FILE}

CITY_CODE = "on-118"
CITY_NAME = "Ottawa"


# Class-level translation keys and their platform domain.
# (translation_key here is the strings.json key — note ec_air_quality vs the
# ec_aqhi unique_id slug: naming and identity are intentionally decoupled.)
CLASS_TRANSLATION_KEYS = {
    ECHourlyForecastSensor: ("sensor", "ec_hourly_forecast"),
    ECDailyForecastSensor: ("sensor", "ec_daily_forecast"),
    ECTodayPopSensor: ("sensor", "ec_precip_probability_today"),
    ECAQHISensor: ("sensor", "ec_air_quality"),
    ECWeatherSummarySensor: ("sensor", "ec_weather_summary"),
    ECAlertCountSensor: ("sensor", "ec_alert_count"),
    ECAlertsSensor: ("sensor", "ec_alerts"),
    ECAlertActiveSensor: ("binary_sensor", "ec_alert_active"),
    ECWeather: ("weather", "ec_weather"),
}


# ---------------------------------------------------------------------------
# EntityDescription-based entities
# ---------------------------------------------------------------------------

class TestDescriptionNaming:
    @pytest.mark.parametrize(
        "description",
        [*CURRENT_SENSOR_DESCRIPTIONS, *GAUGE_SENSOR_DESCRIPTIONS],
        ids=lambda description: description.key,
    )
    def test_description_uses_translation_key_not_name(self, description):
        assert description.translation_key == description.key
        # EntityDescription.name defaults to UNDEFINED; must not be a real label.
        assert description.name in (None, UNDEFINED)


# ---------------------------------------------------------------------------
# Class-level translation keys
# ---------------------------------------------------------------------------

# Constructors differ; build a live instance so we can read the public
# translation_key property (HA's metaclass exposes _attr_translation_key as a
# descriptor at class level, so read it off an instance instead).
def _build_instance(entity_class):
    coordinator = _mock_coordinator()
    weong = _mock_coordinator()
    two_coordinator_classes = {
        ECHourlyForecastSensor,
        ECDailyForecastSensor,
        ECTodayPopSensor,
        ECWeather,
    }
    if entity_class in two_coordinator_classes:
        return entity_class(coordinator, weong, CITY_CODE, CITY_NAME, "en")
    if entity_class is ECWeatherSummarySensor:
        return entity_class(coordinator, CITY_CODE, CITY_NAME, "en")
    return entity_class(coordinator, CITY_CODE, CITY_NAME)


class TestClassNaming:
    @pytest.mark.parametrize(
        "entity_class",
        list(CLASS_TRANSLATION_KEYS),
        ids=lambda cls: cls.__name__,
    )
    def test_class_sets_translation_key_and_no_hardcoded_name(self, entity_class):
        _domain, expected_key = CLASS_TRANSLATION_KEYS[entity_class]
        instance = _build_instance(entity_class)
        assert instance.translation_key == expected_key
        # No hardcoded name literal survives on the class.
        assert "_attr_name" not in entity_class.__dict__


class TestYesterdayPrecipNaming:
    @pytest.mark.parametrize(
        "key", yesterday_precip_sensor_keys("split"), ids=lambda key: key
    )
    def test_instance_translation_key_matches_slug(self, key):
        coordinator = _mock_coordinator()
        sensor = ECYesterdayPrecipSensor(coordinator, key, CITY_CODE, CITY_NAME)
        assert sensor._attr_translation_key == f"ec_{key}"
        # No hardcoded per-instance name.
        assert getattr(sensor, "_attr_name", None) is None


def _mock_coordinator():
    from unittest.mock import MagicMock

    coordinator = MagicMock()
    coordinator.data = None
    return coordinator


# ---------------------------------------------------------------------------
# Translation-file parity (drift guard)
# ---------------------------------------------------------------------------

def _used_keys_by_domain() -> dict[str, set[str]]:
    """Collect every translation_key used in the integration, grouped by domain."""
    used: dict[str, set[str]] = {"sensor": set(), "binary_sensor": set(), "weather": set()}
    for description in (*CURRENT_SENSOR_DESCRIPTIONS, *GAUGE_SENSOR_DESCRIPTIONS):
        used["sensor"].add(description.translation_key)
    for domain, key in CLASS_TRANSLATION_KEYS.values():
        used[domain].add(key)
    for key in ("yesterday_rain", "yesterday_snow", "yesterday_precipitation"):
        used["sensor"].add(f"ec_{key}")
    return used


def _entity_section(path: Path) -> dict:
    return json.loads(path.read_text())["entity"]


class TestTranslationParity:
    @pytest.mark.parametrize("file_label", list(TRANSLATION_FILES), ids=lambda label: label)
    def test_every_used_key_present(self, file_label):
        section = _entity_section(TRANSLATION_FILES[file_label])
        for domain, keys in _used_keys_by_domain().items():
            available = set(section.get(domain, {}))
            missing = keys - available
            assert not missing, f"{file_label}: entity.{domain} missing {sorted(missing)}"

    def test_alert_active_binary_sensor_entry_present(self):
        for file_label, path in TRANSLATION_FILES.items():
            section = _entity_section(path)
            assert "ec_alert_active" in section.get("binary_sensor", {}), (
                f"{file_label} missing entity.binary_sensor.ec_alert_active"
            )

    def test_three_files_share_identical_entity_key_sets(self):
        def flatten(path: Path) -> set[str]:
            section = _entity_section(path)
            return {
                f"{domain}.{key}"
                for domain, entries in section.items()
                for key in entries
            }

        strings_keys = flatten(STRINGS_FILE)
        en_keys = flatten(EN_FILE)
        fr_keys = flatten(FR_FILE)
        assert strings_keys == en_keys, strings_keys.symmetric_difference(en_keys)
        assert strings_keys == fr_keys, strings_keys.symmetric_difference(fr_keys)
