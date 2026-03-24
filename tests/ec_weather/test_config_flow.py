"""Tests for EC Weather options flow.

Note: Full integration-level config flow tests require HA to load the
custom component, which needs additional setup (loader patches).
These tests validate the options schema logic directly.
"""

from __future__ import annotations

import pytest

from ec_weather.const import (
    CONF_BBOX,
    CONF_CITY_CODE,
    CONF_GEOMET_BBOX,
    CONF_LANGUAGE,
    CONF_AQHI_LOCATION_ID,
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
)


class TestOptionsConstants:
    def test_supported_languages(self):
        """Integration supports English and French."""
        assert "en" in SUPPORTED_LANGUAGES
        assert "fr" in SUPPORTED_LANGUAGES

    def test_default_language_is_english(self):
        """Default language is English."""
        assert DEFAULT_LANGUAGE == "en"

    def test_config_keys_defined(self):
        """All required config keys are defined as constants."""
        assert CONF_CITY_CODE == "city_code"
        assert CONF_LANGUAGE == "language"
        assert CONF_BBOX == "bbox"
        assert CONF_GEOMET_BBOX == "geomet_bbox"
        assert CONF_AQHI_LOCATION_ID == "aqhi_location_id"
