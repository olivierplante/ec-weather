"""Tests for the backend-resolved per-half popup precip amounts.

The daily COLUMN (card ``dailyPrecip``) prefers EC-stated accumulation, falling
back to the WEonG model estimate. The popup Day/Night boxes used to read only
the WEonG per-half fields, so an EC-stated amount showed in the column but not
the box. The backend now resolves the per-half display amount ONCE (EC-accum
first, else the WEonG estimate honouring the beta gate + remaining-only trim)
and attaches ``precip_amount_day`` / ``precip_amount_night`` to each daily row;
the popup is pure display over those fields.
"""

from __future__ import annotations

from freezegun import freeze_time

from ec_weather.transforms import build_daily_view, resolve_half_precip


class TestResolveHalfPrecip:
    def test_ec_rain_amount_wins_over_weong(self):
        """An EC-stated mm amount → rain, estimated False (no WEonG needed)."""
        out = resolve_half_precip(5.0, "mm", 2.0, 0.0)
        assert out == {"rain_mm": 5.0, "snow_cm": 0.0, "estimated": False}

    def test_ec_cm_amount_is_snow(self):
        """An EC-stated cm amount → snow (mirrors dailyPrecip's unit split)."""
        out = resolve_half_precip(3.0, "cm", 0.0, 0.0)
        assert out == {"rain_mm": 0.0, "snow_cm": 3.0, "estimated": False}

    def test_falls_back_to_weong_estimate_when_no_ec(self):
        """No EC amount → WEonG per-half figures, estimated True."""
        out = resolve_half_precip(None, None, 1.5, 0.4)
        assert out == {"rain_mm": 1.5, "snow_cm": 0.4, "estimated": True}

    def test_beta_off_weong_none_yields_empty_estimate(self):
        """Beta gate off (WEonG fields None) and no EC → nothing to show."""
        out = resolve_half_precip(None, None, None, None)
        assert out == {"rain_mm": 0.0, "snow_cm": 0.0, "estimated": True}

    def test_zero_ec_amount_is_not_stated(self):
        """A 0 EC amount is not a stated accumulation → WEonG branch."""
        out = resolve_half_precip(0.0, "mm", 2.0, 0.0)
        assert out == {"rain_mm": 2.0, "snow_cm": 0.0, "estimated": True}


class TestBuildDailyViewAttachesResolvedAmounts:
    @freeze_time("2026-07-14T10:00:00Z")
    def test_ec_stated_amount_present_on_both_halves(self):
        daily = [{
            "period": "Wednesday", "date": "2026-07-16",
            "temp_high": 20, "temp_low": 10,
            "precip_accum_amount": 5.0, "precip_accum_unit": "mm",
            "precip_accum_amount_night": 3.0, "precip_accum_unit_night": "cm",
        }]
        view = build_daily_view(daily, {}, [], "2026-07-14",
                                model_precip_estimate=False)
        assert view[0]["precip_amount_day"] == {
            "rain_mm": 5.0, "snow_cm": 0.0, "estimated": False,
        }
        assert view[0]["precip_amount_night"] == {
            "rain_mm": 0.0, "snow_cm": 3.0, "estimated": False,
        }

    @freeze_time("2026-07-14T10:00:00Z")
    def test_weong_estimate_when_no_ec_and_beta_on(self):
        daily = [{
            "period": "Wednesday", "date": "2026-07-16",
            "temp_high": 20, "temp_low": 10,
        }]
        weong = {
            ("2026-07-16", "day"): {"pop": 60, "rain_mm": 2.4, "snow_cm": None, "timesteps": []},
            ("2026-07-16", "night"): {"pop": 40, "rain_mm": None, "snow_cm": 1.1, "timesteps": []},
        }
        view = build_daily_view(daily, weong, [], "2026-07-14",
                                model_precip_estimate=True)
        assert view[0]["precip_amount_day"]["rain_mm"] == 2.4
        assert view[0]["precip_amount_day"]["estimated"] is True
        assert view[0]["precip_amount_night"]["snow_cm"] == 1.1

    @freeze_time("2026-07-14T10:00:00Z")
    def test_outlook_rows_are_not_given_resolved_amounts(self):
        """Outlook rows keep their exact key set (no per-half amount fields)."""
        daily = [{"period": "Tue", "date": "2026-07-14", "temp_high": 20, "temp_low": 10}]
        outlook = [{"date": "2026-07-22", "source": "outlook", "temp_high": 25}]
        view = build_daily_view(daily, {}, [], "2026-07-14", outlook=outlook)
        assert "precip_amount_day" not in view[-1]
        assert view[-1]["source"] == "outlook"
