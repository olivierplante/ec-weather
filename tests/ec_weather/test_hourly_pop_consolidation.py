"""Per-hour POP consolidation between the hourly strip and the daily popup.

The hourly strip (``build_unified_hourly``) and the daily popup timesteps
(``enrich_timesteps``) must resolve a single hour's probability-of-precipitation
IDENTICALLY. Both call the shared ``resolve_hourly_pop`` helper so the rule
cannot drift:

    per-hour POP = WEonG model pop when the WEonG value is not None,
    else fall back to EC citypage ``lop``.

Regression: EC citypage ``lop`` was flat 0/"Nil" for all 24h while WEonG carried
60/56/30/8 beside real rain amounts, so the strip (kept lop) and the popup (kept
WEonG pop) showed different numbers for the same hour.
"""

from __future__ import annotations

from ec_weather.transforms import (
    build_unified_hourly,
    enrich_timesteps,
    resolve_hourly_pop,
)


TS = "2026-03-23T14:00:00Z"


def _ec_hourly_item(dt: str, lop: int | None) -> dict:
    """Minimal EC citypage hourly item carrying an lop-derived POP."""
    return {
        "time": dt,
        "temp": -5,
        "feels_like": -10,
        "condition": "Cloudy",
        "icon_code": 3,
        "precipitation_probability": lop,
        "wind_speed": 20,
        "wind_gust": None,
        "wind_direction": "NW",
    }


def _weong_hourly_item(pop: int | None, rain: float | None = 1.5) -> dict:
    """Minimal WEonG hourly dict (project_hourly / to_hourly_dict shape)."""
    return {
        "rain_mm": rain,
        "snow_cm": None,
        "sky_state": 9,
        "temp": -5,
        "precipitation_probability": pop,
        "freezing_precip_mm": None,
        "ice_pellet_cm": None,
    }


def _weong_timestep(dt: str, pop: int | None, rain: float | None = 1.5) -> dict:
    """Minimal WEonG timestep (project_periods / to_dict shape)."""
    return {
        "time": dt,
        "temp": -5,
        "feels_like": None,
        "icon_code": None,
        "condition": None,
        "precipitation_probability": pop,
        "rain_mm": rain,
        "snow_cm": None,
        "freezing_precip_mm": None,
        "ice_pellet_cm": None,
        "wind_speed": None,
        "wind_gust": None,
        "wind_direction": None,
        "sky_state": 9,
    }


def _strip_pop(ec_lop: int | None, weong_pop: int | None, weong_present: bool = True) -> int | None:
    """Resolve the strip's POP for the shared timestamp."""
    ec_hourly = [_ec_hourly_item(TS, ec_lop)]
    weong_hourly = {TS: _weong_hourly_item(weong_pop)} if weong_present else {}
    result = build_unified_hourly(ec_hourly, weong_hourly)
    return result[0]["precipitation_probability"]


def _popup_pop(ec_lop: int | None, weong_pop: int | None, ec_present: bool = True) -> int | None:
    """Resolve the popup timestep's POP for the shared timestamp."""
    weong_data = {"timesteps": [_weong_timestep(TS, weong_pop)]}
    hourly_lookup = {TS: _ec_hourly_item(TS, ec_lop)} if ec_present else {}
    result = enrich_timesteps(weong_data, hourly_lookup)
    return result[0]["precipitation_probability"]


# ---------------------------------------------------------------------------
# resolve_hourly_pop — the single shared rule
# ---------------------------------------------------------------------------

class TestResolveHourlyPop:
    def test_weong_wins_when_present(self):
        assert resolve_hourly_pop(60, 0) == 60

    def test_weong_zero_is_a_real_value(self):
        # A real 0 from WEonG is not "missing" — it must win over EC lop.
        assert resolve_hourly_pop(0, 30) == 0

    def test_falls_back_to_ec_when_weong_none(self):
        assert resolve_hourly_pop(None, 30) == 30

    def test_both_none(self):
        assert resolve_hourly_pop(None, None) is None


# ---------------------------------------------------------------------------
# Strip (build_unified_hourly) — EC-covered branch
# ---------------------------------------------------------------------------

class TestStripPop:
    def test_ec_covered_hour_uses_weong_pop(self):
        """Live bug reproduction: lop 0, WEonG 60 → strip must show 60."""
        assert _strip_pop(ec_lop=0, weong_pop=60) == 60

    def test_falls_back_to_lop_when_weong_pop_none(self):
        assert _strip_pop(ec_lop=30, weong_pop=None) == 30

    def test_falls_back_to_lop_when_weong_absent(self):
        assert _strip_pop(ec_lop=30, weong_pop=None, weong_present=False) == 30


# ---------------------------------------------------------------------------
# Popup (enrich_timesteps) — symmetry with the strip
# ---------------------------------------------------------------------------

class TestPopupPop:
    def test_ec_covered_hour_uses_weong_pop(self):
        assert _popup_pop(ec_lop=0, weong_pop=60) == 60

    def test_falls_back_to_lop_when_timestep_pop_none(self):
        """enrich_timesteps: timestep pop None + EC lop present → EC value."""
        assert _popup_pop(ec_lop=30, weong_pop=None) == 30

    def test_weong_only_hour_unchanged(self):
        """Beyond EC coverage (no EC hourly) → keeps WEonG pop."""
        assert _popup_pop(ec_lop=None, weong_pop=56, ec_present=False) == 56

# NOTE: the former TestBuildersAgree property (strip == popup across a lop x pop
# matrix, POP only) was dropped — it is a strict subset of
# test_canonical_hourly.py::TestSurfacesProduceIdenticalRecords
# ::test_full_record_matches_across_source_matrix, which asserts full-record
# equality (POP included) across a temp x icon x pop x rain x sky matrix. The
# resolve_hourly_pop unit tests above stay: they localize the rule and cover the
# weong_present=False / ec_present=False fallback branches the canonical matrix
# does not vary.
