"""Tests for the EC Weather icon registry — single source of truth for icon mappings."""

from __future__ import annotations

import re
from pathlib import Path

from ec_weather.icon_registry import ICON_CONDITIONS, ICON_MDI, icon_code_to_condition


class TestIconConditions:
    """ICON_CONDITIONS dict covers all EC icon codes."""

    def test_covers_codes_0_through_48(self):
        expected = set(range(49))
        assert set(ICON_CONDITIONS.keys()) == expected

    def test_all_values_are_strings(self):
        for code, condition in ICON_CONDITIONS.items():
            assert isinstance(condition, str), f"code {code}: expected str, got {type(condition)}"


class TestIconMDI:
    """ICON_MDI dict covers all EC icon codes with MDI icon strings."""

    def test_covers_codes_0_through_48(self):
        expected = set(range(49))
        assert set(ICON_MDI.keys()) == expected

    def test_all_values_start_with_mdi(self):
        for code, mdi in ICON_MDI.items():
            assert mdi.startswith("mdi:"), f"code {code}: {mdi!r} does not start with 'mdi:'"


class TestIconConditionsAndMDIAlignment:
    """ICON_CONDITIONS and ICON_MDI must have identical key sets."""

    def test_same_keys(self):
        assert set(ICON_CONDITIONS.keys()) == set(ICON_MDI.keys())


class TestIconCodeToCondition:
    """icon_code_to_condition maps codes to HA condition strings."""

    def test_none_returns_none(self):
        assert icon_code_to_condition(None) is None

    def test_code_0_returns_sunny(self):
        assert icon_code_to_condition(0) == "sunny"

    def test_code_30_returns_clear_night(self):
        assert icon_code_to_condition(30) == "clear-night"

    def test_unknown_code_returns_cloudy_fallback(self):
        assert icon_code_to_condition(999) == "cloudy"

    def test_negative_code_returns_cloudy_fallback(self):
        assert icon_code_to_condition(-1) == "cloudy"


class TestJSSyncWithPython:
    """JS EC_ICON_MAP keys must match Python ICON_MDI keys."""

    def test_js_keys_match_python_keys(self):
        js_path = (
            Path(__file__).resolve().parents[2]
            / "config"
            / "custom_components"
            / "ec_weather"
            / "www"
            / "ec-weather-card.js"
        )
        js_content = js_path.read_text()

        # Extract the EC_ICON_MAP block
        match = re.search(r"const EC_ICON_MAP\s*=\s*\{([^}]+)\}", js_content)
        assert match, "EC_ICON_MAP not found in ec-weather-card.js"

        # Parse all integer keys from the JS object literal
        js_keys = {int(k) for k in re.findall(r"(\d+)\s*:", match.group(1))}

        assert js_keys == set(ICON_MDI.keys()), (
            f"JS EC_ICON_MAP keys differ from Python ICON_MDI keys. "
            f"Only in JS: {js_keys - set(ICON_MDI.keys())}. "
            f"Only in Python: {set(ICON_MDI.keys()) - js_keys}."
        )
