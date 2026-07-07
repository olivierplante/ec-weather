"""Tests for the redesigned alerts section (Claude Design handoff, commit 2).

Design rules:
  - ONE neutral style for every warning type — no per-severity color on the bar
  - hidden entirely when there is no active alert
  - multiple alerts stack vertically
  - centered bar: alert icon + headline
  - tap-to-expand detail (with expiry line) is preserved behavior
  - uses the shared token CSS + theme class like every redesigned section
"""

from __future__ import annotations

from .conftest import CARD_JS_PATH as CARD_JS


def _alerts_section() -> str:
    source = CARD_JS.read_text()
    start = source.find("_renderAlerts() {")
    end = source.find("_renderCurrent() {", start)
    assert start != -1 and end != -1
    return source[start:end]


class TestNeutralBar:
    def test_no_per_severity_color_lookup(self):
        """The severity → color map must be gone from the banner."""
        section = _alerts_section()
        assert "colors[alert.type]" not in section

    def test_no_severity_color_vars_in_banner(self):
        section = _alerts_section()
        for var in (
            "--ec-weather-alert-warning",
            "--ec-weather-alert-watch",
            "--ec-weather-alert-advisory",
        ):
            assert var not in section, f"{var} must not style the neutral bar"

    def test_design_alert_icon(self):
        assert "mdi:alert-outline" in _alerts_section()

    def test_uses_shared_tokens(self):
        assert "TOKEN_CSS" in _alerts_section()

    def test_theme_class_wrapper(self):
        assert "themeClass" in _alerts_section()


class TestVisibility:
    def test_hidden_when_no_alerts(self):
        section = _alerts_section()
        assert "innerHTML = ''" in section or 'innerHTML = ""' in section

    def test_multiple_alerts_stack(self):
        section = _alerts_section()
        assert "alerts.forEach" in section
        assert "alert-stack" in section


class TestExpandBehavior:
    def test_tap_to_expand_preserved(self):
        section = _alerts_section()
        assert "_expandedAlerts" in section

    def test_expiry_line_preserved(self):
        section = _alerts_section()
        assert "expires" in section

    def test_alert_text_escaped(self):
        """Alert headline/text come from the EC API — must stay escaped."""
        section = _alerts_section()
        assert "escapeHtml" in section
