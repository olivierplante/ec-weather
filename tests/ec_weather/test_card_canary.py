"""JS card canary — the slim residue of the old CARD_JS source-audit family.

The redesign shipped ~145 pytest source-greps that asserted substrings existed
in the hand-written card JS (test_daily_redesign / test_hourly_redesign /
test_alerts_redesign / test_current_layout / test_precip_panel / test_sun_arc /
test_card_groundwork). Both those greps and the vitest suite read the SAME
``www/ec-weather-card.js`` (there is no bundle/build step — see conftest's
CARD_JS_PATH and www/__tests__/*.test.js importing ``../ec-weather-card.js``),
so the greps were a strictly weaker second copy of coverage vitest already
provides behaviorally by rendering the DOM.

They were collapsed into this module. What survives is ONLY what vitest
structurally cannot verify against that same file:

  1. The public ``--ec-weather-*`` CSS override contract. jsdom applies no
     stylesheet and resolves no CSS custom-property cascade, so it cannot prove
     a documented override var still exists to be themed. (Vitest DOES check, on
     the rendered side, that the style blocks reference exactly the canonical
     var set — see render-smoke.test.js "css override token contract"; that
     complements, not replaces, the source-presence guard here.)
  2. Container-query reflow. jsdom computes no layout, so ``@container`` /
     ``container-type`` behavior is unobservable; only their presence can be
     pinned.
  3. The neutral alerts-bar invariant. The shared TOKEN_CSS unconditionally
     carries the legacy ``--ec-weather-alert-*`` vars for back-compat, so a
     rendered alert bar always contains them — a DOM test cannot distinguish a
     neutral bar from a re-colored one. The only robust guard is that
     ``_renderAlerts`` performs no per-severity color lookup.
  4. EN/FR I18N key parity. Vitest renders a single (English) locale and has no
     cross-language key-set assertion; parity is only checkable by parsing both
     translation blocks out of source.

KNOWN LIMITATION (behavioral CSS): none of these prove a ``--ec-weather-*``
override actually WINS at render — that needs a real layout engine (the headless
harness), deliberately not built in this pass. The rendered canonical-list
vitest is the strongest behavioral proxy available under jsdom.

The cross-language EC_ICON_MAP<->Python parity guard lives separately in
test_icon_registry.py::TestJSSyncWithPython (kept untouched).
"""

from __future__ import annotations

from .conftest import CARD_JS_PATH as CARD_JS


def _source() -> str:
    return CARD_JS.read_text()


def _alerts_section() -> str:
    """The _renderAlerts method body (definition, not the shared TOKEN_CSS)."""
    source = _source()
    start = source.find("_renderAlerts() {")
    end = source.find("_renderCurrent() {", start)
    assert start != -1 and end != -1
    return source[start:end]


def _en_block() -> str:
    source = _source()
    return source[source.find("en: {"):source.find("fr: {")]


def _fr_block() -> str:
    source = _source()
    fr_start = source.find("fr: {")
    return source[fr_start:source.find("\n};", fr_start)]


# ---------------------------------------------------------------------------
# 1 — Public --ec-weather-* CSS override contract
#     jsdom resolves no custom-property cascade, so source presence is the only
#     pytest-side guard that the documented theming surface still exists.
# ---------------------------------------------------------------------------

class TestCssOverrideContract:
    # Every documented, user-facing override variable. Removing or renaming any
    # of these silently breaks a customization contract vitest cannot detect.
    PUBLIC_OVERRIDE_VARS = (
        "--ec-weather-text-primary",
        "--ec-weather-text-secondary",
        "--ec-weather-text-muted",
        "--ec-weather-divider",
        "--ec-weather-precip-rain",
        "--ec-weather-precip-snow",
        "--ec-weather-snow-bar",
        "--ec-weather-sun",
        "--ec-weather-sun-arc",
        "--ec-weather-curve",
        "--ec-weather-pop",
        "--ec-weather-hero-icon",
        "--ec-weather-panel-bg",
        "--ec-weather-panel-border",
        "--ec-weather-panel-head",
        "--ec-weather-panel-title",
        "--ec-weather-outlook-opacity",
        "--ec-weather-alert-warning",
        "--ec-weather-alert-border",
    )

    def test_public_override_vars_present(self):
        source = _source()
        for var in self.PUBLIC_OVERRIDE_VARS:
            assert var in source, f"public override var {var} must remain honored"

    def test_temp_scale_override_vars(self):
        """The 8 absolute-temperature buckets each resolve through a public var.
        helpers.test.js proves only that ONE bucket uses the --ec-weather-temp-
        prefix; the full 8-name contract is asserted only here."""
        source = _source()
        for bucket in (
            "frigid", "freezing", "cold", "cool",
            "mild", "warm", "hot", "scorching",
        ):
            assert f"--ec-weather-temp-{bucket}" in source, f"temp bucket {bucket} var missing"

    def test_uv_scale_override_vars(self):
        source = _source()
        for level in ("low", "moderate", "high", "very-high", "extreme"):
            assert f"--ec-weather-uv-{level}" in source, f"uv {level} var missing"

    def test_aqhi_scale_override_vars(self):
        source = _source()
        for level in ("low", "moderate", "high", "very-high"):
            assert f"--ec-weather-aqhi-{level}" in source, f"aqhi {level} var missing"

    def test_token_css_and_ha_theme_neutrals(self):
        """The neutral palette must bind to HA theme vars so the card inherits
        the active theme. jsdom applies no theme, so this binding is invisible
        to a render test."""
        source = _source()
        assert "TOKEN_CSS" in source
        for ha_var in (
            "--primary-text-color",
            "--secondary-text-color",
            "--divider-color",
        ):
            assert ha_var in source, f"neutral must bind to HA {ha_var}"

    def test_light_and_dark_theme_accents(self):
        """Theme-tuned rain accent (#46b0ec dark / #2b8fd1 light) plus the
        light-theme override class — no computed-style needed to regress."""
        source = _source()
        assert "#46b0ec" in source
        assert "#2b8fd1" in source
        assert ".ecc.light" in source


# ---------------------------------------------------------------------------
# 2 — Container-query contract
#     jsdom computes no layout; only presence of the size container + queries
#     can be guarded here (the reflow itself is a headless-harness concern).
# ---------------------------------------------------------------------------

class TestContainerQueryContract:
    def test_size_container_declared(self):
        assert "container-type: inline-size" in _source()

    def test_container_query_breakpoints(self):
        assert "@container" in _source()


# ---------------------------------------------------------------------------
# 3 — Neutral alerts-bar invariant (source-level, not DOM-observable)
#     Shared TOKEN_CSS always carries --ec-weather-alert-* for back-compat, so
#     a rendered bar cannot be proven neutral; guard the code path instead.
# ---------------------------------------------------------------------------

class TestAlertNeutralBarInvariant:
    def test_no_per_severity_color_lookup(self):
        """The old severity -> color map keyed by alert.type must stay gone;
        one neutral style for every warning type."""
        assert "colors[alert.type]" not in _alerts_section()

    def test_severity_vars_absent_from_alert_body(self):
        """The legacy per-severity vars live only in shared TOKEN_CSS; they must
        never be reintroduced into the alert renderer to re-color the bar."""
        section = _alerts_section()
        for var in (
            "--ec-weather-alert-warning",
            "--ec-weather-alert-watch",
            "--ec-weather-alert-advisory",
        ):
            assert var not in section, f"{var} must not style the neutral bar"


# ---------------------------------------------------------------------------
# 4 — EN/FR I18N key parity
#     Vitest renders one (English) locale and never asserts key-set equality
#     across languages; parity is only visible by parsing both blocks.
# ---------------------------------------------------------------------------

class TestI18nKeyParity:
    # Chrome keys the redesign added (current/daily/precip-panel/popup).
    CHROME_KEYS = (
        "precipTitle", "todayForecast", "yesterday", "none", "noneExpected",
        "noData", "calm", "chance", "week", "aqhiLabel", "staleBanner",
        "refresh", "dayDone", "noHourly", "ecAttribution",
    )
    # Sun-arc + polar keys.
    SUN_KEYS = ("sunriseIn", "sunsetIn", "ofDaylight", "sunUpAllDay", "polarNight")

    def test_chrome_keys_in_both_languages(self):
        en, fr = _en_block(), _fr_block()
        for key in self.CHROME_KEYS:
            assert f"{key}:" in en, f"EN chrome key {key} missing"
            assert f"{key}:" in fr, f"FR chrome key {key} missing"

    def test_sun_and_polar_keys_in_both_languages(self):
        en, fr = _en_block(), _fr_block()
        for key in self.SUN_KEYS:
            assert f"{key}:" in en, f"EN sun key {key} missing"
            assert f"{key}:" in fr, f"FR sun key {key} missing"

    def test_french_specific_chrome_strings(self):
        """A couple of translated values pin that the FR block is real content,
        not an EN copy: AQHI is 'CAS' in French, and the dry-forecast header."""
        fr = _fr_block()
        assert "'CAS'" in fr or '"CAS"' in fr
        assert "Aucune prévue" in fr
        assert "None expected" in _en_block()

    def test_combined_station_tooltip_translated(self):
        """The combined-station yesterday tooltip explains the melted water
        equivalent. render-smoke's fixture is opted-in-but-unpublished, so the
        combined path (and this translated string) is never exercised there."""
        lowered = _source().lower()
        assert "combined" in lowered
        assert "water equivalent" in lowered
