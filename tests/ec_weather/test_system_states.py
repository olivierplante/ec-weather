"""Tests for the redesigned system states (Claude Design handoff, commit 6).

  - Entity unavailable / EC unreachable → single "Weather unavailable" state:
    quiet icon + title + explanation + retry button + last-updated time.
    No fake zeros.
  - Transient refresh (WEonG still loading on hourly/daily) → quiet spinner,
    no error styling.
  - Stale but present → slim neutral banner + dimmed card body; the last
    reading stays visible. Threshold: 2 h without a successful update (the
    30-min on-demand refresh fires first, so 2 h means refreshing has
    genuinely been failing).
  - Alerts section still hides entirely when unavailable.
"""

from __future__ import annotations

from .conftest import CARD_JS_PATH as CARD_JS


def _source() -> str:
    return CARD_JS.read_text()


def _unavailable_section() -> str:
    source = _source()
    start = source.find("_renderUnavailable() {")
    end = source.find("_updateDisplay() {", start)
    assert start != -1 and end != -1
    return source[start:end]


def _current_section() -> str:
    source = _source()
    start = source.find("_renderCurrent() {")
    end = source.find("_renderHourly() {", start)
    assert start != -1 and end != -1
    return source[start:end]


class TestUnavailableState:
    def test_design_state_container(self):
        assert "ustate" in _unavailable_section()

    def test_quiet_cloud_off_icon(self):
        assert "mdi:cloud-off-outline" in _unavailable_section()

    def test_title_and_message(self):
        section = _unavailable_section()
        assert "'weatherUnavailable'" in section
        assert "'unavailableMsg'" in section

    def test_retry_button_calls_update_entity(self):
        section = _unavailable_section()
        assert "'retry'" in section
        assert "update_entity" in section

    def test_last_updated_meta(self):
        section = _unavailable_section()
        assert "'updatedAt'" in section
        assert "last_updated" in section

    def test_theme_integration(self):
        section = _unavailable_section()
        assert "TOKEN_CSS" in section
        assert "themeClass" in section

    def test_alerts_still_hidden(self):
        section = _unavailable_section()
        assert "'alerts'" in section


class TestTransientLoading:
    def test_quiet_spinner_no_error_styling(self):
        """WEonG pending on hourly/daily → spinner, not an error box."""
        section = _unavailable_section()
        assert "mdi:loading" in section
        assert "spin" in section

    def test_loading_text(self):
        assert "'loading'" in _unavailable_section()


class TestStaleState:
    def test_banner_in_current_section(self):
        section = _current_section()
        assert "staleBanner" in section
        assert "mdi:clock-alert-outline" in section

    def test_stale_decision_via_heartbeat_helper(self):
        """staleInfo() (vitest-covered) measures the fetch heartbeat, not
        last_updated — stable readings must never trip the banner."""
        assert "staleInfo(" in _current_section()

    def test_card_body_dimmed_but_data_kept(self):
        """Dim the last reading, don't blank it."""
        assert "0.62" in _current_section()

    def test_refresh_action(self):
        section = _current_section()
        assert "'refresh'" in section
        assert "update_entity" in section


class TestUnavailableI18n:
    def test_message_keys_in_both_languages(self):
        source = _source()
        en_block = source[source.find("en: {"):source.find("fr: {")]
        fr_start = source.find("fr: {")
        fr_block = source[fr_start:source.find("\n};", fr_start)]
        assert "unavailableMsg:" in en_block
        assert "unavailableMsg:" in fr_block
