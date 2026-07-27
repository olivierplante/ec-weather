"""Tests for dropping a STALE leading 'Tonight' period from the daily forecast.

EC drops the daytime 'Today' period in the late afternoon, leaving a night-only
'Tonight' as the first forecast entry — that is legitimately tonight and must be
kept. EC ALSO keeps the previous evening's 'Tonight' through the following
morning until its next update; by then that night has passed and the entry is
stale and must be dropped.

The two are structurally identical (temp_high=None). They differ only in time
coverage: a fresh 'Tonight' still has hours ahead in its ``timesteps_night``; a
stale one's hours are all in the past (EC hourly is future-only, so it no longer
feeds them). ``leading_night_is_stale`` distinguishes them by that coverage —
independent of the clock hour, which is what the old hour-window heuristic got
wrong (it dropped the fresh evening Tonight in the 4 PM–6 PM window).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from custom_components.ec_weather.transforms import leading_night_is_stale


def _iso(dt: datetime) -> str:
    """Format a datetime as the Z-suffixed UTC ISO string timesteps carry."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _night_period(timestep_times: list[str]) -> dict:
    """Build a night-only period (temp_high=None) with the given night timesteps."""
    return {
        "period": "Tonight",
        "temp_high": None,
        "temp_low": 17,
        "icon_code": None,
        "icon_code_night": 33,
        "timesteps_day": [],
        "timesteps_night": [{"time": t} for t in timestep_times],
    }


def _full_day_period() -> dict:
    """Build a full day+night period (temp_high set)."""
    return {
        "period": "Wednesday",
        "temp_high": 26,
        "temp_low": 17,
        "icon_code": 1,
        "icon_code_night": 33,
        "timesteps_day": [],
        "timesteps_night": [],
    }


class TestLeadingNightIsStale:
    """Verify stale vs fresh leading-night detection by timestep coverage."""

    def test_fresh_evening_tonight_kept_at_4pm(self) -> None:
        """The regression: EC drops Today at ~4 PM; the fresh Tonight has future
        hours, so it must NOT be treated as stale (the old <18 window dropped it)."""
        now = datetime(2026, 7, 27, 20, 0, tzinfo=timezone.utc)  # 16:00 EDT
        future = [_iso(now + timedelta(hours=h)) for h in (1, 2, 3, 10)]
        assert leading_night_is_stale(_night_period(future), now) is False

    def test_stale_morning_tonight_dropped(self) -> None:
        """A leftover Tonight in the morning has only past hours → stale."""
        now = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)  # 08:00 EDT
        past = [_iso(now - timedelta(hours=h)) for h in (12, 8, 4, 1)]
        assert leading_night_is_stale(_night_period(past), now) is True

    def test_empty_timesteps_is_stale(self) -> None:
        """A night-only period with no timesteps at all is stale (nothing ahead)."""
        now = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
        assert leading_night_is_stale(_night_period([]), now) is True

    def test_overnight_tonight_kept(self) -> None:
        """In the small hours, tonight's remaining hours are still ahead → kept."""
        now = datetime(2026, 7, 27, 6, 0, tzinfo=timezone.utc)  # 02:00 EDT
        future = [_iso(now + timedelta(hours=h)) for h in (1, 2, 3)]
        assert leading_night_is_stale(_night_period(future), now) is False

    def test_full_day_period_never_stale(self) -> None:
        """A full day+night period (temp_high set) is never a stale leading night."""
        now = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
        assert leading_night_is_stale(_full_day_period(), now) is False

    def test_timestep_at_cutoff_is_fresh(self) -> None:
        """A timestep at exactly the next-hour cutoff counts as ahead → kept."""
        now = datetime(2026, 7, 27, 20, 30, tzinfo=timezone.utc)  # cutoff 21:00Z
        cutoff_only = [_iso(datetime(2026, 7, 27, 21, 0, tzinfo=timezone.utc))]
        assert leading_night_is_stale(_night_period(cutoff_only), now) is False

    def test_only_in_progress_hour_left_is_stale(self) -> None:
        """When the sole remaining timestep is the already-elapsing hour (before
        the cutoff), the night is effectively over → stale."""
        now = datetime(2026, 7, 27, 11, 30, tzinfo=timezone.utc)  # cutoff 12:00Z
        elapsing = [_iso(datetime(2026, 7, 27, 11, 0, tzinfo=timezone.utc))]
        assert leading_night_is_stale(_night_period(elapsing), now) is True
