"""Tests for coordinator.extended_helpers — pure GEPS synthesis helpers.

Phase A of the extended-forecast plan (specs/ec_weather/weong-far-days-plan.md).
All helpers are pure: no I/O, no hass, no network. Values are synthetic.

Covers:
  - GEPS layer-name builders + verified layer constants
  - GEPS 12h UTC window mapping (incl. DST fall-back, month/year rolls)
  - synthesize_timestep: every icon-recipe branch, humidex gate, graceful None
  - outlook_day: median scalars, band, per-half POP display threshold,
    the no-dishonest-keys guard
  - outlook_sentence_params: rounded range, dominant POP, amount gate at 50
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from ec_weather.coordinator.extended_helpers import (
    GEPS_AMOUNT_P25,
    GEPS_AMOUNT_P75,
    GEPS_CLOUD_P50,
    GEPS_HUMIDEX_P50,
    GEPS_POP_12H,
    GEPS_RAIN_MEDIAN,
    GEPS_SNOW_MEDIAN,
    GEPS_TEMPERATURE_P25,
    GEPS_TEMPERATURE_P50,
    GEPS_TEMPERATURE_P75,
    _geps_layer,
    geps_window_for,
    outlook_day,
    outlook_sentence_params,
    synthesize_timestep,
    window_covers_period,
)
from ec_weather.icon_registry import (
    CLEAR_NIGHT,
    CLOUDY,
    MOSTLY_CLOUDY_DAY,
    MOSTLY_CLOUDY_NIGHT,
    PARTLY_CLOUDY_DAY,
    PARTLY_CLOUDY_NIGHT,
    RAIN,
    SNOW,
    SUNNY,
)
from ec_weather.timestep_store import TimestepData

TORONTO = ZoneInfo("America/Toronto")

# The two "chance of" icon codes reused from icon_registry's EC vocabulary:
# 6 -> rainy (chance of showers), 8 -> snowy (chance of flurries).
CHANCE_OF_SHOWERS = 6
CHANCE_OF_FLURRIES = 8


def _utc(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# A1 — GEPS layer-name builders and constants
# ---------------------------------------------------------------------------

class TestGepsLayerBuilder:
    @pytest.mark.parametrize(
        "variable,statistic,expected",
        [
            ("TT", "ERC50", "GEPS.DIAG.3_TT.ERC50"),
            ("TT", "ERC25", "GEPS.DIAG.3_TT.ERC25"),
            ("TT", "ERC75", "GEPS.DIAG.3_TT.ERC75"),
            ("HMX", "ERC50", "GEPS.DIAG.3_HMX.ERC50"),
            ("NT", "ERC50", "GEPS.DIAG.3_NT.ERC50"),
            # RNMM/SNMM only exist at the 12h interval (verified live
            # 2026-07-07 — the 3h variant returns InvalidLayersParameter).
            ("RNMM", "ERC50", "GEPS.DIAG.12_RNMM.ERC50"),
            ("SNMM", "ERC50", "GEPS.DIAG.12_SNMM.ERC50"),
            ("PRMM", "ERGE1", "GEPS.DIAG.12_PRMM.ERGE1"),
            ("PRMM", "ERC25", "GEPS.DIAG.12_PRMM.ERC25"),
            ("PRMM", "ERC75", "GEPS.DIAG.12_PRMM.ERC75"),
        ],
    )
    def test_builds_verified_layer_names(self, variable, statistic, expected):
        assert _geps_layer(variable, statistic) == expected

    def test_named_constants_match_verified_strings(self):
        assert GEPS_TEMPERATURE_P25 == "GEPS.DIAG.3_TT.ERC25"
        assert GEPS_TEMPERATURE_P50 == "GEPS.DIAG.3_TT.ERC50"
        assert GEPS_TEMPERATURE_P75 == "GEPS.DIAG.3_TT.ERC75"
        assert GEPS_HUMIDEX_P50 == "GEPS.DIAG.3_HMX.ERC50"
        assert GEPS_CLOUD_P50 == "GEPS.DIAG.3_NT.ERC50"
        assert GEPS_POP_12H == "GEPS.DIAG.12_PRMM.ERGE1"
        assert GEPS_AMOUNT_P25 == "GEPS.DIAG.12_PRMM.ERC25"
        assert GEPS_AMOUNT_P75 == "GEPS.DIAG.12_PRMM.ERC75"
        assert GEPS_RAIN_MEDIAN == "GEPS.DIAG.12_RNMM.ERC50"
        assert GEPS_SNOW_MEDIAN == "GEPS.DIAG.12_SNMM.ERC50"

    def test_pop_uses_12h_interval_others_use_3h(self):
        assert GEPS_POP_12H.startswith("GEPS.DIAG.12_")
        assert GEPS_TEMPERATURE_P50.startswith("GEPS.DIAG.3_")


# ---------------------------------------------------------------------------
# A2 — GEPS 12h window mapping
# ---------------------------------------------------------------------------

class TestGepsWindowFor:
    @pytest.mark.parametrize(
        "ts,expected_start,expected_end",
        [
            # A value AT 12:00Z covers 00Z -> 12Z (spec convention).
            (_utc(2026, 7, 16, 12), _utc(2026, 7, 16, 0), _utc(2026, 7, 16, 12)),
            # A value AT 00:00Z covers the previous 12:00Z -> 00:00Z.
            (_utc(2026, 7, 16, 0), _utc(2026, 7, 15, 12), _utc(2026, 7, 16, 0)),
            # 15:00Z sits in the 12Z -> 00Z(next) window.
            (_utc(2026, 7, 16, 15), _utc(2026, 7, 16, 12), _utc(2026, 7, 17, 0)),
            # 06:00Z / 09:00Z sit in the 00Z -> 12Z window.
            (_utc(2026, 7, 16, 6), _utc(2026, 7, 16, 0), _utc(2026, 7, 16, 12)),
            (_utc(2026, 7, 16, 9), _utc(2026, 7, 16, 0), _utc(2026, 7, 16, 12)),
            (_utc(2026, 7, 16, 21), _utc(2026, 7, 16, 12), _utc(2026, 7, 17, 0)),
            # Month boundary.
            (_utc(2026, 7, 31, 15), _utc(2026, 7, 31, 12), _utc(2026, 8, 1, 0)),
            # Year boundary.
            (_utc(2026, 12, 31, 21), _utc(2026, 12, 31, 12), _utc(2027, 1, 1, 0)),
            (_utc(2027, 1, 1, 0), _utc(2026, 12, 31, 12), _utc(2027, 1, 1, 0)),
        ],
    )
    def test_window_bounds(self, ts, expected_start, expected_end):
        start, end = geps_window_for(ts)
        assert start == expected_start
        assert end == expected_end

    def test_window_is_exactly_twelve_hours(self):
        start, end = geps_window_for(_utc(2026, 7, 16, 15))
        assert (end - start).total_seconds() == 12 * 3600


class TestWindowCoversPeriod:
    def test_summer_day_covered_by_afternoon_window(self):
        # EDT (UTC-4): local day 06-18 == 10:00Z-22:00Z, midpoint 16:00Z.
        day_window = (_utc(2026, 7, 16, 12), _utc(2026, 7, 17, 0))
        morning_window = (_utc(2026, 7, 16, 0), _utc(2026, 7, 16, 12))
        assert window_covers_period(*day_window, "2026-07-16", "day", TORONTO)
        assert not window_covers_period(
            *morning_window, "2026-07-16", "day", TORONTO
        )

    def test_summer_night_covered_by_morning_window(self):
        # Night midpoint lands after midnight UTC -> the 00Z-12Z window.
        morning_window = (_utc(2026, 7, 17, 0), _utc(2026, 7, 17, 12))
        evening_window = (_utc(2026, 7, 16, 12), _utc(2026, 7, 17, 0))
        assert window_covers_period(
            *morning_window, "2026-07-16", "night", TORONTO
        )
        assert not window_covers_period(
            *evening_window, "2026-07-16", "night", TORONTO
        )

    def test_dst_fallback_night_spans_transition(self):
        # Night of 2026-10-31 spans the fall-back (EDT->EST at 02:00 local
        # Nov 1). It is a 13h night: 22:00Z Oct31 -> 11:00Z Nov1, midpoint
        # 04:30Z Nov1, covered by the 00Z-12Z Nov1 window.
        morning_window = (_utc(2026, 11, 1, 0), _utc(2026, 11, 1, 12))
        assert window_covers_period(
            *morning_window, "2026-10-31", "night", TORONTO
        )

    def test_dst_after_fallback_day_shifted_by_offset(self):
        # After fall-back Toronto is EST (UTC-5): local day 06-18 on Nov 1
        # == 11:00Z-23:00Z, midpoint 17:00Z, still the 12Z-00Z window.
        day_window = (_utc(2026, 11, 1, 12), _utc(2026, 11, 2, 0))
        assert window_covers_period(*day_window, "2026-11-01", "day", TORONTO)

    def test_non_overlapping_window_does_not_cover(self):
        far_window = (_utc(2026, 7, 20, 0), _utc(2026, 7, 20, 12))
        assert not window_covers_period(
            *far_window, "2026-07-16", "day", TORONTO
        )


# ---------------------------------------------------------------------------
# A3 — synthesize_timestep
# ---------------------------------------------------------------------------

# A daytime UTC hour (6 <= h < 18) and a nighttime one for icon variants.
DAY_TS = "2026-07-16T15:00:00Z"
NIGHT_TS = "2026-07-16T03:00:00Z"


class TestSynthesizeTimestepType:
    def test_returns_timestep_data(self):
        result = synthesize_timestep(DAY_TS, 20.0, None, 40.0, 10, None, None)
        assert isinstance(result, TimestepData)
        assert result.time == DAY_TS
        assert result.model == "geps"

    def test_temp_and_pop_populated_and_rounded(self):
        result = synthesize_timestep(DAY_TS, 21.34, None, 40.0, 55.6, None, None)
        assert result.temp == 21.3
        assert result.pop == 56

    def test_amounts_are_never_per_timestep(self):
        # Window-spanning amounts render separately -> per-step amounts absent.
        result = synthesize_timestep(DAY_TS, 20.0, None, 40.0, 70, 5.0, 0.0)
        assert result.rain_mm is None
        assert result.snow_cm is None


class TestSynthesizeTimestepIcon:
    def test_high_pop_rain_dominant_is_rain(self):
        result = synthesize_timestep(DAY_TS, 12.0, None, 90.0, 80, 6.0, 0.0)
        assert result.icon_code == RAIN

    def test_high_pop_snow_dominant_is_snow(self):
        result = synthesize_timestep(DAY_TS, -5.0, None, 90.0, 80, 0.0, 4.0)
        assert result.icon_code == SNOW

    def test_high_pop_no_medians_warm_defaults_rain(self):
        result = synthesize_timestep(DAY_TS, 5.0, None, 90.0, 70, None, None)
        assert result.icon_code == RAIN

    def test_high_pop_no_medians_cold_defaults_snow(self):
        result = synthesize_timestep(DAY_TS, -3.0, None, 90.0, 70, None, None)
        assert result.icon_code == SNOW

    def test_high_pop_equal_medians_temp_tiebreak_cold(self):
        result = synthesize_timestep(DAY_TS, -1.0, None, 90.0, 70, 2.0, 2.0)
        assert result.icon_code == SNOW

    def test_high_pop_equal_medians_temp_tiebreak_warm(self):
        result = synthesize_timestep(DAY_TS, 3.0, None, 90.0, 70, 2.0, 2.0)
        assert result.icon_code == RAIN

    def test_chance_band_rain_dominant_is_chance_of_showers(self):
        result = synthesize_timestep(DAY_TS, 14.0, None, 70.0, 45, 3.0, 0.1)
        assert result.icon_code == CHANCE_OF_SHOWERS

    def test_chance_band_snow_dominant_is_chance_of_flurries(self):
        result = synthesize_timestep(DAY_TS, -4.0, None, 70.0, 45, 0.1, 2.0)
        assert result.icon_code == CHANCE_OF_FLURRIES

    @pytest.mark.parametrize(
        "cloud,day_code,night_code",
        [
            (10.0, SUNNY, CLEAR_NIGHT),
            (24.9, SUNNY, CLEAR_NIGHT),
            (25.0, PARTLY_CLOUDY_DAY, PARTLY_CLOUDY_NIGHT),
            (59.9, PARTLY_CLOUDY_DAY, PARTLY_CLOUDY_NIGHT),
            (60.0, MOSTLY_CLOUDY_DAY, MOSTLY_CLOUDY_NIGHT),
            (84.9, MOSTLY_CLOUDY_DAY, MOSTLY_CLOUDY_NIGHT),
            (85.0, CLOUDY, CLOUDY),
            (100.0, CLOUDY, CLOUDY),
        ],
    )
    def test_dry_cloud_buckets_day_and_night(self, cloud, day_code, night_code):
        day = synthesize_timestep(DAY_TS, 15.0, None, cloud, 10, None, None)
        night = synthesize_timestep(NIGHT_TS, 8.0, None, cloud, 10, None, None)
        assert day.icon_code == day_code
        assert night.icon_code == night_code

    def test_pop_29_is_below_precip_threshold_uses_cloud(self):
        result = synthesize_timestep(DAY_TS, 15.0, None, 90.0, 29, 5.0, 0.0)
        assert result.icon_code == CLOUDY

    def test_missing_pop_falls_back_to_cloud_bucket(self):
        result = synthesize_timestep(DAY_TS, 15.0, None, 10.0, None, None, None)
        assert result.icon_code == SUNNY


class TestSynthesizeTimestepFeelsLike:
    @pytest.mark.parametrize(
        "temp,humidex,expected",
        [
            (25.0, 30.0, 30.0),      # hot + humid -> humidex
            (25.0, 25.4, None),      # humidex < temp + 1 -> None
            (18.0, 25.0, None),      # temp < 20 -> None
            (20.0, 21.0, 21.0),      # exactly at the gate boundary
            (20.0, 20.9, None),      # just below temp + 1
            (None, 30.0, None),      # no temp -> None
            (25.0, None, None),      # no humidex -> None
        ],
    )
    def test_humidex_gate(self, temp, humidex, expected):
        result = synthesize_timestep(DAY_TS, temp, humidex, 40.0, 10, None, None)
        assert result.feels_like == expected


class TestSynthesizeTimestepGracefulNone:
    def test_missing_temp_still_valid(self):
        result = synthesize_timestep(DAY_TS, None, None, 10.0, 10, None, None)
        assert result.temp is None
        assert result.icon_code == SUNNY  # cloud bucket still works

    def test_no_pop_no_cloud_yields_no_icon(self):
        result = synthesize_timestep(DAY_TS, 15.0, None, None, None, None, None)
        assert result.icon_code is None

    def test_everything_none_is_empty_compatible(self):
        result = synthesize_timestep(DAY_TS, None, None, None, None, None, None)
        public = result.to_dict()
        # Mirrors the card's isEmptyTimestep(): temp / icon_code / pop all null.
        assert public["temp"] is None
        assert public["icon_code"] is None
        assert public["precipitation_probability"] is None
        assert result.rain_mm is None
        assert result.snow_cm is None


# ---------------------------------------------------------------------------
# A4 — outlook_day
# ---------------------------------------------------------------------------

def _outlook(**overrides):
    params = dict(
        date_str="2026-07-16",
        tt_low_p25=11.0,
        tt_low_p50=13.0,
        tt_high_p50=24.0,
        tt_high_p75=27.0,
        pop_day=55,
        pop_night=20,
        amt_p25=4.0,
        amt_p75=9.0,
        nt_day_p50=70.0,
        nt_night_p50=30.0,
        rain_med=5.0,
        snow_med=0.0,
        hmx_day_p50=28.0,
        hmx_night_p50=15.0,
    )
    params.update(overrides)
    return outlook_day(**params)


class TestOutlookDay:
    def test_median_scalars(self):
        result = _outlook()
        assert result["temp_low"] == 13.0
        assert result["temp_high"] == 24.0

    def test_temp_range_uses_p25_low_and_p75_high(self):
        result = _outlook()
        assert result["temp_range"] == {"low": 11.0, "high": 27.0}

    def test_source_is_outlook(self):
        assert _outlook()["source"] == "outlook"

    def test_raw_pop_always_kept(self):
        result = _outlook(pop_day=55, pop_night=20)
        assert result["pop_day"] == 55
        assert result["pop_night"] == 20

    def test_pop_display_threshold(self):
        result = _outlook(pop_day=55, pop_night=20)
        assert result["pop_day_display"] == 55   # >= 30 shows
        assert result["pop_night_display"] is None  # < 30 hidden

    def test_pop_display_exactly_30_shows(self):
        result = _outlook(pop_day=30, pop_night=29)
        assert result["pop_day_display"] == 30
        assert result["pop_night_display"] is None

    def test_pop_display_rounds_up_to_next_five(self):
        """The >= 30 gate is on the RAW value, but the shown number is stepped
        by the shared display_pop rule (round up to the next 5)."""
        result = _outlook(pop_day=33, pop_night=31)
        assert result["pop_day_display"] == 35
        assert result["pop_night_display"] == 35

    def test_pop_display_raw_gate_below_thirty_hidden_even_though_it_would_round_to_thirty(self):
        """A raw 28 rounds to 30, but the gate is on the raw value (< 30) so it
        stays hidden — the outlook list's stricter boundary is unchanged."""
        result = _outlook(pop_day=28, pop_night=26)
        assert result["pop_day_display"] is None
        assert result["pop_night_display"] is None

    def test_icons_per_half_via_recipe(self):
        # Day: pop 55 (chance band) rain-dominant -> chance of showers.
        # Night: pop 20 (dry) cloud 30% -> partly cloudy night.
        result = _outlook(
            pop_day=55, rain_med=5.0, snow_med=0.0,
            pop_night=20, nt_night_p50=30.0,
        )
        assert result["icon_day"] == CHANCE_OF_SHOWERS
        assert result["icon_night"] == PARTLY_CLOUDY_NIGHT

    def test_amount_band_present_when_wet(self):
        result = _outlook(pop_day=60, pop_night=20, amt_p25=4.0, amt_p75=9.0)
        assert result["amount_band"] == {"low": 4.0, "high": 9.0}

    def test_amount_band_none_when_dry(self):
        result = _outlook(pop_day=40, pop_night=20)
        assert result["amount_band"] is None

    def test_feels_like_day_gated_by_humidex(self):
        result = _outlook(tt_high_p50=24.0, hmx_day_p50=28.0)
        assert result["feels_like_day"] == 28.0

    def test_feels_like_night_none_when_cold(self):
        result = _outlook(tt_low_p50=13.0, hmx_night_p50=15.0)
        assert result["feels_like_night"] is None

    def test_no_dishonest_scalar_keys(self):
        result = _outlook()
        for forbidden in (
            "humidity", "wind_speed", "wind_gust", "wind_direction",
            "condition", "text_summary", "temp_high_p50",
        ):
            assert forbidden not in result


# ---------------------------------------------------------------------------
# A5 — outlook_sentence_params
# ---------------------------------------------------------------------------

class TestOutlookSentenceParams:
    def test_rounded_range(self):
        result = outlook_sentence_params(
            tt_low_p25=11.4, tt_high_p75=26.6,
            pop_day=40, pop_night=20, amt_p25=4.0, amt_p75=9.0,
        )
        assert result["range_low"] == 11
        assert result["range_high"] == 27

    def test_dominant_pop_is_max_half(self):
        result = outlook_sentence_params(
            tt_low_p25=11.0, tt_high_p75=27.0,
            pop_day=40, pop_night=65, amt_p25=4.0, amt_p75=9.0,
        )
        assert result["dominant_pop"] == 65

    def test_amount_band_present_at_50(self):
        result = outlook_sentence_params(
            tt_low_p25=11.0, tt_high_p75=27.0,
            pop_day=50, pop_night=20, amt_p25=4.0, amt_p75=9.0,
        )
        assert result["amount_band"] == {"low": 4.0, "high": 9.0}

    def test_amount_band_absent_below_50(self):
        result = outlook_sentence_params(
            tt_low_p25=11.0, tt_high_p75=27.0,
            pop_day=49, pop_night=20, amt_p25=4.0, amt_p75=9.0,
        )
        assert result["amount_band"] is None

    def test_missing_pop_halves_degrade(self):
        result = outlook_sentence_params(
            tt_low_p25=11.0, tt_high_p75=27.0,
            pop_day=None, pop_night=None, amt_p25=None, amt_p75=None,
        )
        assert result["dominant_pop"] is None
        assert result["amount_band"] is None
