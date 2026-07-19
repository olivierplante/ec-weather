"""Tests for build_daily_view — the shared merge+remaining-trim daily helper.

``build_daily_view`` is the single place the daily merge
(``merge_weong_into_daily``) and the in-progress re-projection
(``apply_remaining_only``) run in lockstep, so the daily sensor, the today-POP
sensor and the weather entity can never do one without the other.
"""

from __future__ import annotations

from freezegun import freeze_time

from ec_weather.transforms import (
    apply_remaining_only,
    build_daily_view,
    merge_weong_into_daily,
)


def _without_resolved(view: list[dict]) -> list[dict]:
    """Strip the popup-only resolved-amount keys build_daily_view adds, so the
    merge+trim core can be compared against the hand-written pair."""
    out = []
    for period in view:
        stripped = dict(period)
        stripped.pop("precip_amount_day", None)
        stripped.pop("precip_amount_night", None)
        out.append(stripped)
    return out


def _ts(time_iso: str, pop: int, rain: float) -> dict:
    return {"time": time_iso, "precipitation_probability": pop, "rain_mm": rain}


def _daily(date: str) -> dict:
    return {
        "period": "Tuesday",
        "date": date,
        "temp_high": 24,
        "temp_low": 12,
        "icon_code": 1,
        "icon_code_night": 30,
    }


class TestBuildDailyViewEquivalence:
    @freeze_time("2026-07-14T19:30:00Z")
    def test_matches_manual_merge_then_trim(self):
        """The helper equals merge_weong_into_daily + apply_remaining_only."""
        daily = [_daily("2026-07-14"), _daily("2026-07-15")]
        weong_periods = {
            ("2026-07-14", "day"): {
                "pop": 60, "rain_mm": 4.0, "snow_cm": None,
                "timesteps": [
                    _ts("2026-07-14T16:00:00Z", 40, 1.0),
                    _ts("2026-07-14T21:00:00Z", 60, 3.0),
                ],
            },
            ("2026-07-14", "night"): {
                "pop": 30, "rain_mm": 1.0, "snow_cm": None, "timesteps": [],
            },
        }
        hourly = []
        today = "2026-07-14"

        manual = merge_weong_into_daily(
            daily, weong_periods, hourly, lang="en",
            model_precip_estimate=True,
        )
        apply_remaining_only(manual, today, model_precip_estimate=True)

        shared = build_daily_view(
            daily, weong_periods, hourly, today, lang="en",
            model_precip_estimate=True,
        )
        assert _without_resolved(shared) == manual

    @freeze_time("2026-07-14T19:30:00Z")
    def test_trims_the_in_progress_day(self):
        """Today's straddling day period re-aggregates over remaining hours."""
        daily = [_daily("2026-07-14")]
        weong_periods = {
            ("2026-07-14", "day"): {
                "pop": 60, "rain_mm": 4.0, "snow_cm": None,
                "timesteps": [
                    _ts("2026-07-14T16:00:00Z", 40, 1.0),   # elapsed
                    _ts("2026-07-14T21:00:00Z", 55, 3.0),   # remaining
                ],
            },
        }
        view = build_daily_view(daily, weong_periods, [], "2026-07-14")
        # Only the 21:00 timestep is still ahead → its POP wins, elapsed dropped.
        assert view[0]["precip_prob_day"] == 55
        assert len(view[0]["timesteps_day"]) == 1

    @freeze_time("2026-07-14T19:30:00Z")
    def test_threads_all_optional_params_like_the_daily_sensor(self):
        """Outlook rows, precip windows and backfill flow through unchanged."""
        daily = [_daily("2026-07-14")]
        outlook = [{"date": "2026-07-22", "source": "outlook", "temp_high": 25}]
        manual = merge_weong_into_daily(
            daily, {}, [], lang="en", outlook=outlook, model_precip_estimate=False,
        )
        apply_remaining_only(manual, "2026-07-14", model_precip_estimate=False)
        shared = build_daily_view(
            daily, {}, [], "2026-07-14", outlook=outlook,
            model_precip_estimate=False,
        )
        assert _without_resolved(shared) == manual
        assert shared[-1]["source"] == "outlook"
