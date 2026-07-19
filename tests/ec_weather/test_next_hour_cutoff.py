"""Direct unit tests for transforms.next_hour_cutoff.

The cutoff is the single boundary every "what's ahead" hourly surface shares
(the hourly strip filter and the in-progress-period recompute both call it), so
it feeds every today-value on the card. It was previously exercised only
indirectly through apply_remaining_only / the hourly sensor; these pin its
floor/next-hour rule and formatting at the boundaries directly.

Rule: cutoff = floor(now, hour) + 1h — the in-progress hour is excluded even
exactly on the hour — rendered as ISO-UTC "%Y-%m-%dT%H:%M:%SZ".
"""

from __future__ import annotations

from datetime import datetime, timezone

from ec_weather.transforms import next_hour_cutoff


class TestNextHourCutoff:
    def test_top_of_hour_still_advances_to_next_hour(self):
        """Exactly on the hour, the in-progress hour is already partly elapsed,
        so the cutoff is the NEXT hour, not the current one."""
        now = datetime(2026, 7, 14, 21, 0, 0, tzinfo=timezone.utc)
        assert next_hour_cutoff(now) == "2026-07-14T22:00:00Z"

    def test_mid_hour_floors_then_adds_one_hour(self):
        now = datetime(2026, 7, 14, 21, 30, 45, tzinfo=timezone.utc)
        assert next_hour_cutoff(now) == "2026-07-14T22:00:00Z"

    def test_last_microsecond_of_hour(self):
        now = datetime(2026, 7, 14, 21, 59, 59, 999999, tzinfo=timezone.utc)
        assert next_hour_cutoff(now) == "2026-07-14T22:00:00Z"

    def test_rolls_over_midnight_into_the_next_day(self):
        now = datetime(2026, 7, 14, 23, 30, tzinfo=timezone.utc)
        assert next_hour_cutoff(now) == "2026-07-15T00:00:00Z"

    def test_dst_agnostic_resolves_on_the_utc_wall_clock(self):
        """A US spring-forward date is treated purely by its UTC wall clock — no
        local-time DST shift is ever applied."""
        now = datetime(2026, 3, 8, 6, 45, tzinfo=timezone.utc)
        assert next_hour_cutoff(now) == "2026-03-08T07:00:00Z"

    def test_default_now_is_a_future_top_of_hour_within_one_hour(self):
        before = datetime.now(timezone.utc)
        cutoff = next_hour_cutoff()
        parsed = datetime.strptime(cutoff, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc,
        )
        # Always a whole hour, strictly ahead of the call, at most ~1h out
        # (1s tolerance absorbs a call that straddles an hour boundary).
        assert parsed.minute == 0 and parsed.second == 0
        assert before < parsed
        assert (parsed - before).total_seconds() <= 3601
