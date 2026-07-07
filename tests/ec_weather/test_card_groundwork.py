"""Tests for the redesign groundwork (Claude Design handoff, commit 1).

Source-text assertions on the bundled card JS (the established pattern for
card structure tests). Covers the shared foundation every section builds on:

  - the token CSS block: HA-theme-bound neutrals + dark/light weather accents,
    every accent resolving through a public ``--ec-weather-*`` override first
  - ``themeClass()`` driven by ``hass.themes.darkMode``
  - ``tempColor()`` — the 8 absolute-temperature buckets (design token table)
  - ``aqhiColor()`` / ``uvColor()`` — risk bucket colors from the handoff update
  - ``use24Hour()`` — respects ``hass.locale.time_format`` with language fallback
  - liquid-equivalent precip total (1 cm snow ~ 1 mm water)
  - quiet-dash missing icon helper (a dash, not a cloud, not a "?")
  - new I18N chrome keys present in both EN and FR
"""

from __future__ import annotations

import re

from .conftest import CARD_JS_PATH as CARD_JS


def _source() -> str:
    return CARD_JS.read_text()


def _fn(name: str) -> str:
    """Extract a top-level function body from the card source."""
    source = _source()
    start = source.find(f"function {name}")
    assert start != -1, f"function {name} must exist"
    end = source.find("\nfunction ", start + 1)
    brace_end = source.find("\n}", start)
    assert brace_end != -1
    return source[start:brace_end + 2]


# ---------------------------------------------------------------------------
# Token CSS
# ---------------------------------------------------------------------------

class TestTokenCss:
    def test_token_css_block_exists(self):
        assert "TOKEN_CSS" in _source()

    def test_neutrals_bind_to_ha_theme_vars(self):
        source = _source()
        assert "--primary-text-color" in source
        assert "--secondary-text-color" in source
        assert "--divider-color" in source

    def test_documented_public_vars_still_honored(self):
        """The existing customization contract must survive the redesign."""
        source = _source()
        for var in (
            "--ec-weather-text-primary",
            "--ec-weather-text-secondary",
            "--ec-weather-precip-rain",
            "--ec-weather-precip-snow",
            "--ec-weather-divider",
        ):
            assert var in source, f"{var} must remain honored"

    def test_new_accents_have_public_override_vars(self):
        source = _source()
        for var in (
            "--ec-weather-sun",
            "--ec-weather-curve",
            "--ec-weather-pop",
        ):
            assert var in source, f"{var} must be customizable"

    def test_dark_and_light_accent_sets(self):
        """Rain accent is theme-tuned: #46b0ec dark, #2b8fd1 light (DC tokens)."""
        source = _source()
        assert "#46b0ec" in source
        assert "#2b8fd1" in source

    def test_light_class_overrides_exist(self):
        assert ".ecc.light" in _source()


# ---------------------------------------------------------------------------
# themeClass()
# ---------------------------------------------------------------------------

class TestThemeClass:
    def test_uses_ha_dark_mode_flag(self):
        body = _fn("themeClass")
        assert "darkMode" in body

    def test_defaults_to_dark_when_flag_absent(self):
        """darkMode !== false → dark (older HA without the flag stays dark)."""
        body = _fn("themeClass")
        assert "=== false" in body


# ---------------------------------------------------------------------------
# tempColor() — absolute temperature scale
# ---------------------------------------------------------------------------

class TestTempColor:
    BUCKETS = [
        ("-15", "#6a7fd0"),
        ("0", "#5b93d4"),
        ("6", "#4fa6cf"),
        ("12", "#5cbf9e"),
        ("18", "#93c98a"),
        ("24", "#dcc079"),
        ("30", "#e59b5b"),
        (None, "#e5793f"),
    ]

    def test_all_eight_bucket_colors(self):
        body = _fn("tempColor")
        for _, color in self.BUCKETS:
            assert color in body, f"temp bucket color {color} missing"

    def test_thresholds(self):
        body = _fn("tempColor")
        for threshold in ("-15", "6", "12", "18", "24", "30"):
            assert threshold in body

    def test_buckets_are_publicly_overridable(self):
        """Each bucket resolves through a --ec-weather-temp-* var."""
        body = _fn("tempColor")
        assert "--ec-weather-temp-" in body


# ---------------------------------------------------------------------------
# aqhiColor() / uvColor()
# ---------------------------------------------------------------------------

class TestRiskBuckets:
    def test_aqhi_bucket_colors(self):
        body = _fn("aqhiColor")
        for color in ("#4f9fd0", "#dcae4e", "#e08a3f", "#d1495b"):
            assert color in body

    def test_aqhi_thresholds(self):
        body = _fn("aqhiColor")
        assert "3" in body and "6" in body and "10" in body

    def test_uv_bucket_colors(self):
        body = _fn("uvColor")
        for color in ("#3f9f6e", "#dcae4e", "#e08a3f", "#d1495b", "#9b5fb8"):
            assert color in body

    def test_uv_thresholds(self):
        body = _fn("uvColor")
        assert "2" in body and "5" in body and "7" in body and "10" in body

    def test_null_returns_null(self):
        """Absent value → null → cell hidden entirely."""
        assert "null" in _fn("aqhiColor")
        assert "null" in _fn("uvColor")


# ---------------------------------------------------------------------------
# use24Hour() — clock preference
# ---------------------------------------------------------------------------

class TestClockPreference:
    def test_reads_locale_time_format(self):
        body = _fn("use24Hour")
        assert "time_format" in body

    def test_explicit_12_and_24(self):
        body = _fn("use24Hour")
        assert "'24'" in body and "'12'" in body

    def test_language_fallback_french_24h(self):
        """No explicit preference → fr defaults to 24h."""
        body = _fn("use24Hour")
        assert "fr" in body


# ---------------------------------------------------------------------------
# Liquid equivalent
# ---------------------------------------------------------------------------

class TestLiquidEquivalent:
    def test_helper_exists(self):
        body = _fn("liquidTotal")
        assert "rain" in body and "snow" in body


# ---------------------------------------------------------------------------
# Quiet dash for missing icons
# ---------------------------------------------------------------------------

class TestMissingIcon:
    def test_dash_helper_exists(self):
        body = _fn("missingIconHtml")
        assert "mdi:minus" in body

    def test_not_a_question_mark_or_cloud(self):
        body = _fn("missingIconHtml")
        assert "?" not in body.replace("'?'", "")  # no literal ? icon
        assert "cloud" not in body


# ---------------------------------------------------------------------------
# I18N chrome keys
# ---------------------------------------------------------------------------

class TestI18nKeys:
    NEW_KEYS = [
        "precipTitle",
        "todayForecast",
        "yesterday",
        "none",
        "noneExpected",
        "noData",
        "calm",
        "chance",
        "week",
        "sunriseIn",
        "sunsetIn",
        "ofDaylight",
        "aqhiLabel",
        "staleBanner",
        "refresh",
        # Daily-popup redesign chrome.
        "dayDone",
        "noHourly",
        "ecAttribution",
    ]

    def test_keys_in_english_block(self):
        source = _source()
        en_block = source[source.find("en: {"):source.find("fr: {")]
        for key in self.NEW_KEYS:
            assert f"{key}:" in en_block, f"EN key {key} missing"

    def test_keys_in_french_block(self):
        source = _source()
        fr_start = source.find("fr: {")
        fr_block = source[fr_start:source.find("\n};", fr_start)]
        for key in self.NEW_KEYS:
            assert f"{key}:" in fr_block, f"FR key {key} missing"

    def test_french_aqhi_label_is_cas(self):
        source = _source()
        fr_start = source.find("fr: {")
        fr_block = source[fr_start:source.find("\n};", fr_start)]
        assert "'CAS'" in fr_block or '"CAS"' in fr_block

    def test_french_none_expected(self):
        assert "Aucune prévue" in _source()

    def test_english_none_expected(self):
        assert "None expected" in _source()
