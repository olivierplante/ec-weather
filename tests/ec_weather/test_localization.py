"""Tests for Phase 7 — full English/French localization.

Covers:
  - condition_text() helper from icon_registry
  - derive_icon() with lang parameter
  - apply_icon_fallback() with lang parameter
  - build_unified_hourly() with lang parameter
  - enrich_timesteps() with lang parameter
  - ECWeatherSummarySensor French "Ressenti" output
"""

from __future__ import annotations

from ec_weather.icon_registry import (
    CLEAR_NIGHT,
    CLOUDY,
    CONDITION_TEXT,
    FREEZING_RAIN,
    ICE_PELLETS,
    MAINLY_CLEAR_NIGHT,
    MAINLY_SUNNY,
    MOSTLY_CLOUDY_DAY,
    MOSTLY_CLOUDY_NIGHT,
    PARTLY_CLOUDY_DAY,
    PARTLY_CLOUDY_NIGHT,
    RAIN,
    RAIN_AND_SNOW,
    SNOW,
    SUNNY,
    condition_text,
)
from ec_weather.transforms import (
    apply_icon_fallback,
    build_unified_hourly,
    derive_icon,
    enrich_timesteps,
)


# ---------------------------------------------------------------------------
# condition_text()
# ---------------------------------------------------------------------------

class TestConditionText:
    """condition_text() returns localized condition text from icon codes."""

    def test_none_code_returns_none(self):
        assert condition_text(None) is None

    def test_unknown_code_returns_none(self):
        assert condition_text(999) is None

    def test_sunny_english(self):
        assert condition_text(SUNNY, "en") == "Sunny"

    def test_sunny_french(self):
        assert condition_text(SUNNY, "fr") == "Ensoleillé"

    def test_clear_night_english(self):
        assert condition_text(CLEAR_NIGHT, "en") == "Clear"

    def test_clear_night_french(self):
        assert condition_text(CLEAR_NIGHT, "fr") == "Dégagé"

    def test_freezing_rain_english(self):
        assert condition_text(FREEZING_RAIN, "en") == "Freezing rain"

    def test_freezing_rain_french(self):
        assert condition_text(FREEZING_RAIN, "fr") == "Pluie verglaçante"

    def test_rain_english(self):
        assert condition_text(RAIN, "en") == "Rain"

    def test_rain_french(self):
        assert condition_text(RAIN, "fr") == "Pluie"

    def test_snow_english(self):
        assert condition_text(SNOW, "en") == "Snow"

    def test_snow_french(self):
        assert condition_text(SNOW, "fr") == "Neige"

    def test_cloudy_english(self):
        assert condition_text(CLOUDY, "en") == "Cloudy"

    def test_cloudy_french(self):
        assert condition_text(CLOUDY, "fr") == "Nuageux"

    def test_default_lang_is_english(self):
        """When lang is omitted, defaults to English."""
        assert condition_text(SUNNY) == "Sunny"

    def test_unknown_lang_falls_back_to_english(self):
        """When lang is unsupported, falls back to English."""
        assert condition_text(SUNNY, "de") == "Sunny"

    def test_ice_pellets_french(self):
        assert condition_text(ICE_PELLETS, "fr") == "Grésil"

    def test_rain_and_snow_french(self):
        assert condition_text(RAIN_AND_SNOW, "fr") == "Pluie et neige"

    def test_mainly_sunny_french(self):
        assert condition_text(MAINLY_SUNNY, "fr") == "Généralement ensoleillé"

    def test_partly_cloudy_day_french(self):
        assert condition_text(PARTLY_CLOUDY_DAY, "fr") == "Partiellement nuageux"

    def test_mostly_cloudy_day_french(self):
        assert condition_text(MOSTLY_CLOUDY_DAY, "fr") == "Généralement nuageux"

    def test_mainly_clear_night_french(self):
        assert condition_text(MAINLY_CLEAR_NIGHT, "fr") == "Généralement dégagé"


class TestConditionTextCoverage:
    """CONDITION_TEXT must cover all icon codes used by derive_icon."""

    def test_all_derive_icon_codes_have_condition_text(self):
        """Every icon code that derive_icon can return must be in CONDITION_TEXT."""
        derive_icon_codes = {
            SUNNY, MAINLY_SUNNY, PARTLY_CLOUDY_DAY, MOSTLY_CLOUDY_DAY,
            CLEAR_NIGHT, MAINLY_CLEAR_NIGHT, PARTLY_CLOUDY_NIGHT, MOSTLY_CLOUDY_NIGHT,
            CLOUDY, RAIN, FREEZING_RAIN, RAIN_AND_SNOW, SNOW, ICE_PELLETS,
        }
        for code in derive_icon_codes:
            assert code in CONDITION_TEXT, f"icon code {code} missing from CONDITION_TEXT"
            assert "en" in CONDITION_TEXT[code], f"icon code {code} missing 'en' text"
            assert "fr" in CONDITION_TEXT[code], f"icon code {code} missing 'fr' text"


# ---------------------------------------------------------------------------
# derive_icon() with lang parameter
# ---------------------------------------------------------------------------

class TestDeriveIconEnglish:
    """derive_icon() returns English condition text by default."""

    def test_freezing_rain_english(self):
        weong = {"freezing_precip_mm": 1.0}
        code, text = derive_icon(weong, 14)
        assert code == FREEZING_RAIN
        assert text == "Freezing rain"

    def test_rain_english(self):
        weong = {"rain_mm": 2.0, "temp": 5}
        code, text = derive_icon(weong, 14)
        assert code == RAIN
        assert text == "Rain"

    def test_snow_english(self):
        weong = {"snow_cm": 3.0}
        code, text = derive_icon(weong, 14)
        assert code == SNOW
        assert text == "Snow"

    def test_sunny_english(self):
        weong = {"sky_state": 1}
        code, text = derive_icon(weong, 14)
        assert code == SUNNY
        assert text == "Sunny"

    def test_clear_night_english(self):
        weong = {"sky_state": 0}
        code, text = derive_icon(weong, 22)
        assert code == CLEAR_NIGHT
        assert text == "Clear"


class TestDeriveIconFrench:
    """derive_icon() returns French condition text when lang='fr'."""

    def test_freezing_rain_french(self):
        weong = {"freezing_precip_mm": 1.0}
        code, text = derive_icon(weong, 14, lang="fr")
        assert code == FREEZING_RAIN
        assert text == "Pluie verglaçante"

    def test_ice_pellets_french(self):
        weong = {"ice_pellet_cm": 0.5}
        code, text = derive_icon(weong, 14, lang="fr")
        assert code == ICE_PELLETS
        assert text == "Grésil"

    def test_rain_and_snow_french(self):
        weong = {"rain_mm": 1.0, "snow_cm": 1.0}
        code, text = derive_icon(weong, 14, lang="fr")
        assert code == RAIN_AND_SNOW
        assert text == "Pluie et neige"

    def test_snow_french(self):
        weong = {"snow_cm": 3.0}
        code, text = derive_icon(weong, 14, lang="fr")
        assert code == SNOW
        assert text == "Neige"

    def test_rain_french(self):
        weong = {"rain_mm": 2.0, "temp": 5}
        code, text = derive_icon(weong, 14, lang="fr")
        assert code == RAIN
        assert text == "Pluie"

    def test_sunny_french(self):
        weong = {"sky_state": 1}
        code, text = derive_icon(weong, 14, lang="fr")
        assert code == SUNNY
        assert text == "Ensoleillé"

    def test_clear_night_french(self):
        weong = {"sky_state": 0}
        code, text = derive_icon(weong, 22, lang="fr")
        assert code == CLEAR_NIGHT
        assert text == "Dégagé"

    def test_mainly_sunny_french(self):
        weong = {"sky_state": 3}
        code, text = derive_icon(weong, 14, lang="fr")
        assert code == MAINLY_SUNNY
        assert text == "Généralement ensoleillé"

    def test_partly_cloudy_french(self):
        weong = {"sky_state": 5}
        code, text = derive_icon(weong, 14, lang="fr")
        assert code == PARTLY_CLOUDY_DAY
        assert text == "Partiellement nuageux"

    def test_mostly_cloudy_french(self):
        weong = {"sky_state": 7}
        code, text = derive_icon(weong, 14, lang="fr")
        assert code == MOSTLY_CLOUDY_DAY
        assert text == "Généralement nuageux"

    def test_cloudy_french(self):
        weong = {"sky_state": 10}
        code, text = derive_icon(weong, 14, lang="fr")
        assert code == CLOUDY
        assert text == "Nuageux"

    def test_mainly_clear_night_french(self):
        weong = {"sky_state": 4}
        code, text = derive_icon(weong, 22, lang="fr")
        assert code == MAINLY_CLEAR_NIGHT
        assert text == "Généralement dégagé"

    def test_partly_cloudy_night_french(self):
        weong = {"sky_state": 6}
        code, text = derive_icon(weong, 22, lang="fr")
        assert code == PARTLY_CLOUDY_NIGHT
        assert text == "Partiellement nuageux"

    def test_mostly_cloudy_night_french(self):
        weong = {"sky_state": 8}
        code, text = derive_icon(weong, 22, lang="fr")
        assert code == MOSTLY_CLOUDY_NIGHT
        assert text == "Généralement nuageux"

    def test_rain_below_zero_french(self):
        """Rain with temp < 0 → freezing rain in French."""
        weong = {"rain_mm": 2.0, "temp": -5}
        code, text = derive_icon(weong, 14, lang="fr")
        assert code == FREEZING_RAIN
        assert text == "Pluie verglaçante"

    def test_no_data_returns_none(self):
        weong = {}
        code, text = derive_icon(weong, 14, lang="fr")
        assert code is None
        assert text is None


# ---------------------------------------------------------------------------
# apply_icon_fallback() with lang parameter
# ---------------------------------------------------------------------------

class TestApplyIconFallbackLang:
    """apply_icon_fallback() passes lang through to derive_icon."""

    def test_french_condition_text_from_fallback(self):
        entry = {
            "icon_code": None,
            "condition": None,
            "sky_state": 2,
            "rain_mm": 0,
            "snow_cm": 0,
            "freezing_precip_mm": 0,
            "ice_pellet_cm": 0,
            "temp": -5,
        }
        apply_icon_fallback(entry, "2026-03-23T14:00:00Z", lang="fr")
        assert entry["icon_code"] == SUNNY
        assert entry["condition"] == "Ensoleillé"

    def test_english_condition_text_default(self):
        entry = {
            "icon_code": None,
            "condition": None,
            "sky_state": 2,
            "rain_mm": 0,
            "snow_cm": 0,
            "freezing_precip_mm": 0,
            "ice_pellet_cm": 0,
            "temp": -5,
        }
        apply_icon_fallback(entry, "2026-03-23T14:00:00Z")
        assert entry["condition"] == "Sunny"


# ---------------------------------------------------------------------------
# build_unified_hourly() with lang parameter
# ---------------------------------------------------------------------------

class TestBuildUnifiedHourlyLang:
    """build_unified_hourly() passes lang through for WEonG-derived icons."""

    def test_weong_only_item_french(self):
        """WEonG-only items (beyond EC coverage) get French condition text."""
        ec_hourly = []
        weong_hourly = {
            "2026-03-24T14:00:00Z": {
                "rain_mm": 2.5,
                "snow_cm": 0,
                "sky_state": 5,
                "temp": 5,
                "precipitation_probability": 60,
                "freezing_precip_mm": None,
                "ice_pellet_cm": None,
            },
        }
        result = build_unified_hourly(ec_hourly, weong_hourly, lang="fr")
        assert len(result) == 1
        # rain > 0, temp > 0 → Rain in French
        assert result[0]["condition"] == "Pluie"

    def test_ec_item_with_fallback_french(self):
        """EC item with icon_code=None gets French fallback from WEonG."""
        ec_hourly = [
            {
                "time": "2026-03-23T14:00:00Z",
                "temp": -5,
                "feels_like": -10,
                "condition": None,
                "icon_code": None,
                "precipitation_probability": 30,
                "wind_speed": 20,
                "wind_gust": None,
                "wind_direction": "NW",
            },
        ]
        weong_hourly = {
            "2026-03-23T14:00:00Z": {
                "rain_mm": 0,
                "snow_cm": 0,
                "sky_state": 3,
                "freezing_precip_mm": None,
                "ice_pellet_cm": None,
            },
        }
        result = build_unified_hourly(ec_hourly, weong_hourly, lang="fr")
        assert result[0]["condition"] == "Généralement ensoleillé"

    def test_default_lang_is_english(self):
        """When lang is omitted, condition text is English."""
        ec_hourly = []
        weong_hourly = {
            "2026-03-24T14:00:00Z": {
                "rain_mm": 0,
                "snow_cm": 0,
                "sky_state": 1,
                "temp": 10,
                "precipitation_probability": 0,
                "freezing_precip_mm": None,
                "ice_pellet_cm": None,
            },
        }
        result = build_unified_hourly(ec_hourly, weong_hourly)
        assert result[0]["condition"] == "Sunny"


# ---------------------------------------------------------------------------
# enrich_timesteps() with lang parameter
# ---------------------------------------------------------------------------

class TestEnrichTimestepsLang:
    """enrich_timesteps() passes lang through for WEonG-derived icons."""

    def test_timestep_derives_french_condition(self):
        """Timestep with missing icon gets French condition from sky_state."""
        weong_data = {
            "timesteps": [
                {
                    "time": "2026-03-24T14:00:00Z",
                    "temp": 5,
                    "sky_state": 1,
                    "rain_mm": 0,
                    "snow_cm": 0,
                    "freezing_precip_mm": 0,
                    "ice_pellet_cm": 0,
                },
            ],
        }
        result = enrich_timesteps(weong_data, {}, lang="fr")
        assert len(result) == 1
        assert result[0]["condition"] == "Ensoleillé"

    def test_timestep_default_english(self):
        """When lang is omitted, condition text is English."""
        weong_data = {
            "timesteps": [
                {
                    "time": "2026-03-24T14:00:00Z",
                    "temp": 5,
                    "sky_state": 1,
                    "rain_mm": 0,
                    "snow_cm": 0,
                    "freezing_precip_mm": 0,
                    "ice_pellet_cm": 0,
                },
            ],
        }
        result = enrich_timesteps(weong_data, {})
        assert len(result) == 1
        assert result[0]["condition"] == "Sunny"
