"""Tests for the in-progress period projecting only what's still ahead.

Change 1: for the period that CONTAINS now, POP and expected rain/snow amounts
must aggregate over the REMAINING timesteps only (window start = the next full
hour), so the daily estimate never counts rain that already fell. Wholly-future
periods are untouched.

Consistency edge (supersedes 92d69c6's conservative choice): for TODAY's row a
wholly-past sub-period contributes NOTHING to any user-facing today value — its
POP and amount fields are nulled so the combined ``precip_prob``, the today-POP
sensor, the weather entity, and the card's per-half ``dailyPrecip`` max all show
the same remaining-only (what's-ahead) value. Invariant enforced at any frozen
clock: combined today POP == card's max(per-half pops) == max POP over the row's
remaining timesteps; amounts stay coherent the same way. Other days untouched.

The recompute runs at RENDER time (the daily sensor re-projects on every state
read), so the value shrinks hour by hour with no refetch — proven here with a
frozen clock read at two points.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from freezegun import freeze_time
from homeassistant.core import HomeAssistant

from ec_weather.sensor import ECDailyForecastSensor
from ec_weather.transforms import apply_remaining_only, next_hour_cutoff


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(iso: str, pop: int | None, rain: float | None = None,
        snow: float | None = None) -> dict:
    """A displayed timestep dict as it appears in timesteps_day/night."""
    return {
        "time": iso,
        "precipitation_probability": pop,
        "rain_mm": rain,
        "snow_cm": snow,
    }


def _today_row(*, timesteps_night: list[dict], rain_mm_night: float | None,
               precip_prob_night: int | None,
               timesteps_day: list[dict] | None = None,
               rain_mm_day: float | None = None,
               precip_prob_day: int | None = None,
               date: str = "2026-03-23") -> dict:
    """A merged daily row carrying full-window totals + per-hour timesteps."""
    return {
        "date": date,
        "timesteps_day": timesteps_day or [],
        "timesteps_night": timesteps_night,
        "precip_prob_day": precip_prob_day,
        "rain_mm_day": rain_mm_day,
        "snow_cm_day": None,
        "precip_prob_night": precip_prob_night,
        "rain_mm_night": rain_mm_night,
        "snow_cm_night": None,
        "precip_prob": max(
            [p for p in (precip_prob_day, precip_prob_night) if p is not None]
            or [None]
        ) if (precip_prob_day is not None or precip_prob_night is not None) else None,
    }


def _now(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# apply_remaining_only — the in-progress period
# ---------------------------------------------------------------------------

class TestInProgressPeriodRemaining:
    """The period containing now counts only the hours still ahead."""

    def test_counts_only_remaining_hours(self):
        """At 22:30, 22:00 has elapsed → estimate drops it, counts 23:00 + 00:00."""
        row = _today_row(
            timesteps_night=[
                _ts("2026-03-23T22:00:00Z", pop=100, rain=4.0),
                _ts("2026-03-23T23:00:00Z", pop=100, rain=4.0),
                _ts("2026-03-24T00:00:00Z", pop=100, rain=4.0),
            ],
            rain_mm_night=12.0,   # full-window expectation (4+4+4)
            precip_prob_night=100,
        )
        merged = [row]

        apply_remaining_only(merged, "2026-03-23", now=_now("2026-03-23T22:30:00Z"))

        # Cutoff is the next full hour (23:00): the 22:00 hour is dropped.
        assert merged[0]["rain_mm_night"] == 8.0
        assert [t["time"] for t in merged[0]["timesteps_night"]] == [
            "2026-03-23T23:00:00Z", "2026-03-24T00:00:00Z",
        ]
        assert merged[0]["precip_prob_night"] == 100

    def test_estimate_shrinks_as_hours_pass(self):
        """Same data, two later clocks → the estimate strictly shrinks (no refetch)."""
        timesteps = [
            _ts("2026-03-23T22:00:00Z", pop=100, rain=4.0),
            _ts("2026-03-23T23:00:00Z", pop=100, rain=4.0),
            _ts("2026-03-24T00:00:00Z", pop=100, rain=4.0),
        ]

        early = [_today_row(timesteps_night=list(timesteps),
                            rain_mm_night=12.0, precip_prob_night=100)]
        late = [_today_row(timesteps_night=list(timesteps),
                           rain_mm_night=12.0, precip_prob_night=100)]

        apply_remaining_only(early, "2026-03-23", now=_now("2026-03-23T22:30:00Z"))
        apply_remaining_only(late, "2026-03-23", now=_now("2026-03-23T23:30:00Z"))

        assert early[0]["rain_mm_night"] == 8.0
        assert late[0]["rain_mm_night"] == 4.0   # only 00:00 remains
        assert late[0]["rain_mm_night"] < early[0]["rain_mm_night"]

    def test_expected_value_weights_by_pop(self):
        """Remaining recompute uses the probability-weighted expected amount."""
        row = _today_row(
            timesteps_night=[
                _ts("2026-03-23T22:00:00Z", pop=100, rain=4.0),   # elapsed
                _ts("2026-03-23T23:00:00Z", pop=50, rain=4.0),    # 2.0 expected
                _ts("2026-03-24T00:00:00Z", pop=50, rain=4.0),    # 2.0 expected
            ],
            rain_mm_night=8.0,
            precip_prob_night=100,
        )
        merged = [row]

        apply_remaining_only(merged, "2026-03-23", now=_now("2026-03-23T22:30:00Z"))

        assert merged[0]["rain_mm_night"] == 4.0   # 2.0 + 2.0
        assert merged[0]["precip_prob_night"] == 50  # max of remaining POPs

    def test_trace_floor_hides_sub_measurable_remaining(self):
        """A remaining expectation below 1.0 mm reports None (0.4 mm hides)."""
        row = _today_row(
            timesteps_night=[
                _ts("2026-03-23T22:00:00Z", pop=100, rain=6.0),   # elapsed
                _ts("2026-03-23T23:00:00Z", pop=40, rain=1.0),    # 0.4 remaining
            ],
            rain_mm_night=6.4,
            precip_prob_night=100,
        )
        merged = [row]

        apply_remaining_only(merged, "2026-03-23", now=_now("2026-03-23T22:30:00Z"))

        assert merged[0]["rain_mm_night"] is None

    def test_model_estimate_off_suppresses_amount_keeps_pop(self):
        """With the estimate option off, the recomputed amount is None; POP flows."""
        row = _today_row(
            timesteps_night=[
                _ts("2026-03-23T22:00:00Z", pop=80, rain=4.0),
                _ts("2026-03-23T23:00:00Z", pop=60, rain=4.0),
            ],
            rain_mm_night=None,   # gated off at merge time
            precip_prob_night=80,
        )
        merged = [row]

        apply_remaining_only(
            merged, "2026-03-23", now=_now("2026-03-23T22:30:00Z"),
            model_precip_estimate=False,
        )

        assert merged[0]["rain_mm_night"] is None
        assert merged[0]["precip_prob_night"] == 60   # remaining-only max POP
        assert merged[0]["precip_prob"] == 60


class TestWhollyPastAndFuture:
    """Wholly-future periods are unchanged; a wholly-past sub-period of today is
    excluded entirely from every user-facing today value (new contract)."""

    def test_wholly_future_row_untouched(self):
        """A future-date row keeps its full-window totals and timesteps."""
        future = {
            "date": "2026-03-24",
            "timesteps_day": [_ts("2026-03-24T14:00:00Z", pop=50, rain=6.0)],
            "timesteps_night": [],
            "precip_prob_day": 50,
            "rain_mm_day": 3.0,
            "snow_cm_day": None,
            "precip_prob_night": None,
            "rain_mm_night": None,
            "snow_cm_night": None,
            "precip_prob": 50,
        }
        merged = [future]

        apply_remaining_only(merged, "2026-03-23", now=_now("2026-03-23T22:30:00Z"))

        assert merged[0]["rain_mm_day"] == 3.0
        assert len(merged[0]["timesteps_day"]) == 1

    def test_wholly_past_subperiod_excluded_entirely(self):
        """NEW CONTRACT (rewritten from 92d69c6's ``keeps_total``): today's
        daytime, fully elapsed by night, contributes NOTHING to any today value.

        The superseded test asserted the past day kept its stored 8.0 mm / 80%
        and that they leaked into the combined POP (91-beside-60 divergence).
        Now every day field is nulled: the row shows only the night's remaining."""
        row = _today_row(
            timesteps_day=[
                _ts("2026-03-23T14:00:00Z", pop=80, rain=5.0),  # morning, elapsed
                _ts("2026-03-23T16:00:00Z", pop=80, rain=5.0),
            ],
            rain_mm_day=8.0,
            precip_prob_day=80,
            timesteps_night=[
                _ts("2026-03-23T22:00:00Z", pop=60, rain=4.0),
                _ts("2026-03-23T23:00:00Z", pop=60, rain=4.0),
            ],
            rain_mm_night=8.0,
            precip_prob_night=60,
        )
        merged = [row]

        apply_remaining_only(merged, "2026-03-23", now=_now("2026-03-23T22:30:00Z"))

        # Day is wholly past → excluded from every field, timesteps emptied.
        assert merged[0]["rain_mm_day"] is None
        assert merged[0]["precip_prob_day"] is None
        assert merged[0]["snow_cm_day"] is None
        assert merged[0]["timesteps_day"] == []
        # Night straddles → shrinks to the single remaining hour (0.6 * 4.0).
        assert merged[0]["rain_mm_night"] == 2.4
        assert merged[0]["precip_prob_night"] == 60
        # Combined POP == the night's remaining only — the past day cannot linger.
        assert merged[0]["precip_prob"] == 60

    def test_other_date_rows_never_touched(self):
        """Only the today row is mutated; a different date passed as today is a no-op."""
        row = _today_row(
            timesteps_night=[_ts("2026-03-23T22:00:00Z", pop=100, rain=4.0),
                             _ts("2026-03-23T23:00:00Z", pop=100, rain=4.0)],
            rain_mm_night=8.0,
            precip_prob_night=100,
        )
        merged = [row]

        apply_remaining_only(merged, "2099-01-01", now=_now("2026-03-23T22:30:00Z"))

        assert merged[0]["rain_mm_night"] == 8.0
        assert len(merged[0]["timesteps_night"]) == 2


class TestCoherenceStripEqualsEstimate:
    """The estimate equals the POP-weighted sum over exactly the hours the
    trimmed timestep list can show (same window start)."""

    def test_estimate_matches_visible_timesteps(self):
        row = _today_row(
            timesteps_night=[
                _ts("2026-03-23T22:00:00Z", pop=100, rain=3.0),
                _ts("2026-03-23T23:00:00Z", pop=50, rain=6.0),
                _ts("2026-03-24T00:00:00Z", pop=100, rain=2.0),
            ],
            rain_mm_night=8.0,
            precip_prob_night=100,
        )
        merged = [row]

        apply_remaining_only(merged, "2026-03-23", now=_now("2026-03-23T22:30:00Z"))

        visible = merged[0]["timesteps_night"]
        hand = round(
            sum(t["precipitation_probability"] / 100.0 * t["rain_mm"] for t in visible),
            1,
        )
        assert merged[0]["rain_mm_night"] == hand


class TestTodaySurfacesAlwaysMatch:
    """The top-of-card today POP (combined ``precip_prob``) and the Today/Tonight
    row the card max()es over (``dailyPrecip``) ALWAYS agree, on the
    remaining-only value, across every phase of the clock.

    ``_card_pop`` mirrors the card's ``dailyPrecip`` max over the per-half POP
    fields; ``_remaining_max_pop`` is the independent source of truth (max POP
    over the row's timesteps still at/after the cutoff)."""

    @staticmethod
    def _card_pop(row: dict) -> int:
        """max(popDay||0, popNight||0) — exactly what dailyPrecip max()es over."""
        return max(row.get("precip_prob_day") or 0, row.get("precip_prob_night") or 0)

    @staticmethod
    def _remaining_max_pop(day_ts: list[dict], night_ts: list[dict], cutoff: str) -> int:
        """Truth: highest POP among all timesteps still at/after the cutoff.

        Wholly-past sub-periods have no such timestep, so they contribute nothing."""
        pops = [
            ts["precipitation_probability"]
            for ts in list(day_ts) + list(night_ts)
            if ts.get("time", "") >= cutoff
            and ts.get("precipitation_probability") is not None
        ]
        return max(pops) if pops else 0

    def test_midafternoon_day_straddling(self):
        """Day straddles the cutoff: both surfaces show the remaining day-max, and
        the day's already-elapsed peak (12:00/14:00 at 91%) does not linger."""
        day_ts = [
            _ts("2026-03-23T12:00:00Z", pop=91, rain=4.0),   # elapsed
            _ts("2026-03-23T14:00:00Z", pop=91, rain=4.0),   # elapsed
            _ts("2026-03-23T16:00:00Z", pop=70, rain=4.0),   # remaining
        ]
        night_ts = [
            _ts("2026-03-23T22:00:00Z", pop=60, rain=4.0),
            _ts("2026-03-23T23:00:00Z", pop=60, rain=4.0),
        ]
        row = _today_row(
            timesteps_day=list(day_ts), rain_mm_day=12.0, precip_prob_day=91,
            timesteps_night=list(night_ts), rain_mm_night=8.0, precip_prob_night=60,
        )
        merged = [row]

        now = _now("2026-03-23T14:30:00Z")
        apply_remaining_only(merged, "2026-03-23", now=now)
        cutoff = next_hour_cutoff(now)  # 15:00

        # Remaining day-max is 70 (16:00); it beats the untouched-future night 60.
        assert merged[0]["precip_prob_day"] == 70
        assert merged[0]["precip_prob"] == 70
        assert self._card_pop(merged[0]) == 70
        assert merged[0]["precip_prob"] == self._remaining_max_pop(day_ts, night_ts, cutoff)

    def test_early_evening_day_present_but_past(self):
        """Day half still present in the row but wholly past: excluded everywhere;
        both surfaces show the night's remaining. This is the window between the
        day period's end and EC's Today→Tonight row swap."""
        day_ts = [
            _ts("2026-03-23T12:00:00Z", pop=91, rain=5.0),
            _ts("2026-03-23T14:00:00Z", pop=91, rain=5.0),
            _ts("2026-03-23T16:00:00Z", pop=91, rain=5.0),
        ]
        night_ts = [
            _ts("2026-03-23T20:00:00Z", pop=60, rain=4.0),
            _ts("2026-03-23T22:00:00Z", pop=60, rain=4.0),
            _ts("2026-03-23T23:00:00Z", pop=60, rain=4.0),
        ]
        row = _today_row(
            timesteps_day=list(day_ts), rain_mm_day=13.65, precip_prob_day=91,
            timesteps_night=list(night_ts), rain_mm_night=7.2, precip_prob_night=60,
        )
        merged = [row]

        now = _now("2026-03-23T19:30:00Z")
        apply_remaining_only(merged, "2026-03-23", now=now)
        cutoff = next_hour_cutoff(now)  # 20:00

        # Day wholly past → nulled everywhere (no 91 lingering).
        assert merged[0]["precip_prob_day"] is None
        assert merged[0]["rain_mm_day"] is None
        assert merged[0]["timesteps_day"] == []
        # Night wholly future → untouched. Both surfaces show 60.
        assert merged[0]["precip_prob"] == 60
        assert self._card_pop(merged[0]) == 60
        assert merged[0]["precip_prob"] == self._remaining_max_pop(day_ts, night_ts, cutoff)
        # Amount coherence: card's total rain (day+night) counts only the night.
        card_rain = (merged[0]["rain_mm_day"] or 0) + (merged[0]["rain_mm_night"] or 0)
        assert card_rain == merged[0]["rain_mm_night"]

    def test_tonight_only_unchanged(self):
        """The pre-existing Tonight-only case: no day half, night straddles.
        Behaviour is unchanged — day fields stay None, combined == night remaining."""
        night_ts = [
            _ts("2026-03-23T22:00:00Z", pop=100, rain=4.0),  # elapsed
            _ts("2026-03-23T23:00:00Z", pop=70, rain=4.0),   # remaining
            _ts("2026-03-24T00:00:00Z", pop=70, rain=4.0),   # remaining
        ]
        row = _today_row(
            timesteps_night=list(night_ts), rain_mm_night=12.0, precip_prob_night=100,
        )
        merged = [row]

        now = _now("2026-03-23T22:30:00Z")
        apply_remaining_only(merged, "2026-03-23", now=now)
        cutoff = next_hour_cutoff(now)  # 23:00

        assert merged[0]["precip_prob_day"] is None
        assert merged[0]["precip_prob_night"] == 70
        assert merged[0]["precip_prob"] == 70
        assert self._card_pop(merged[0]) == 70
        assert merged[0]["precip_prob"] == self._remaining_max_pop([], night_ts, cutoff)

    def test_invariant_holds_across_all_clocks(self):
        """Property-style: at EVERY clock the combined today POP equals the card's
        per-half max equals the independent remaining-max over the row's timesteps.

        Clocks span before-day, day-straddling, day-past/night-future,
        night-straddling, and night-almost-done."""
        day_ts = [
            _ts("2026-03-23T12:00:00Z", pop=91, rain=4.0),
            _ts("2026-03-23T14:00:00Z", pop=80, rain=4.0),
            _ts("2026-03-23T16:00:00Z", pop=70, rain=4.0),
        ]
        night_ts = [
            _ts("2026-03-23T20:00:00Z", pop=60, rain=4.0),
            _ts("2026-03-23T22:00:00Z", pop=50, rain=4.0),
            _ts("2026-03-24T00:00:00Z", pop=40, rain=4.0),
        ]
        clocks = [
            "2026-03-23T10:00:00Z",  # before the day period
            "2026-03-23T14:30:00Z",  # day straddling
            "2026-03-23T19:30:00Z",  # day past, night future
            "2026-03-23T22:30:00Z",  # night straddling
            "2026-03-23T23:30:00Z",  # night almost done
        ]
        for clock in clocks:
            row = _today_row(
                timesteps_day=list(day_ts), rain_mm_day=10.0, precip_prob_day=91,
                timesteps_night=list(night_ts), rain_mm_night=6.0, precip_prob_night=60,
            )
            merged = [row]
            now = _now(clock)
            apply_remaining_only(merged, "2026-03-23", now=now)
            cutoff = next_hour_cutoff(now)

            expected = self._remaining_max_pop(day_ts, night_ts, cutoff)
            combined = merged[0]["precip_prob"] or 0
            assert combined == expected, f"combined POP diverged at {clock}"
            assert self._card_pop(merged[0]) == expected, f"card POP diverged at {clock}"


# ---------------------------------------------------------------------------
# Render-time shrink through the actual daily sensor (stateless re-projection)
# ---------------------------------------------------------------------------

class TestDailySensorRenderTimeShrink:
    """extra_state_attributes re-projects on every read, so the estimate shrinks
    as hours pass with no coordinator refetch."""

    def _sensor(self) -> ECDailyForecastSensor:
        weather = MagicMock()
        weather.last_update_success = True
        weather.data = {
            "daily": [{
                "period": "Monday", "date": "2026-03-23",
                "temp_high": 5, "temp_low": -2,
                "icon_code": 12, "icon_code_night": 12,
                "condition_day": "Rain", "condition_night": "Rain",
                "text_summary_day": "Rain.", "text_summary_night": "Rain.",
            }],
            "hourly": [],
            "updated": "2026-03-23T20:00:00Z",
        }
        night_timesteps = [
            {"time": "2026-03-23T22:00:00Z", "precipitation_probability": 100,
             "rain_mm": 4.0, "snow_cm": None, "sky_state": None},
            {"time": "2026-03-23T23:00:00Z", "precipitation_probability": 100,
             "rain_mm": 4.0, "snow_cm": None, "sky_state": None},
            {"time": "2026-03-24T00:00:00Z", "precipitation_probability": 100,
             "rain_mm": 4.0, "snow_cm": None, "sky_state": None},
        ]
        weong = MagicMock()
        weong.data = {
            "periods": {
                ("2026-03-23", "day"): {
                    "pop": None, "rain_mm": None, "snow_cm": None, "timesteps": [],
                },
                ("2026-03-23", "night"): {
                    "pop": 100, "rain_mm": 12.0, "snow_cm": None,
                    "timesteps": night_timesteps,
                },
            },
            "updated": "2026-03-23T20:00:00Z",
            "days_fetched": ["2026-03-23"],
            "precip_windows": None,
            "outlook": None,
            "outlook_backfill": None,
        }
        return ECDailyForecastSensor(
            weather, weong, "on-118", "Ottawa", "en", model_precip_estimate=True,
        )

    def _tonight_rain(self, sensor: ECDailyForecastSensor) -> float | None:
        forecast = sensor.extra_state_attributes["forecast"]
        row = next(item for item in forecast if item.get("date") == "2026-03-23")
        return row["rain_mm_night"]

    def test_shrinks_between_two_reads_without_refetch(self, hass: HomeAssistant):
        sensor = self._sensor()

        with freeze_time("2026-03-23T22:30:00Z"):
            early = self._tonight_rain(sensor)
        with freeze_time("2026-03-23T23:30:00Z"):
            late = self._tonight_rain(sensor)

        # 22:30 → remaining 23:00 + 00:00 = 8.0; 23:30 → only 00:00 = 4.0.
        assert early == 8.0
        assert late == 4.0
        assert late < early
