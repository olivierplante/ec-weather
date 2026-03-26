"""Tests for SkyState preservation across WEonG refreshes.

Phase B replaced the manual carry-forward workaround with the canonical
TimestepStore, which preserves sky_state by construction (merge semantics:
None doesn't overwrite existing non-None values).

These tests verify the store-based preservation behavior that replaced
the old _async_update_data carry-forward code.
"""

from __future__ import annotations

from ec_weather.timestep_store import TimestepData, TimestepStore


class TestSkyStatePreservation:
    """Verify sky_state values survive a full WEonG refresh via the store."""

    def test_sky_state_survives_phase1_refresh(self) -> None:
        """sky_state from lazy fetch survives when Phase 1+2 data refreshes."""
        store = TimestepStore()

        # Phase 1+2: initial data
        store.merge(TimestepData(
            time="2026-03-25T12:00:00Z", pop=0, temp=-3.0, model="hrdps",
        ))
        # Phase 3: lazy SkyState fetch
        store.merge(TimestepData(
            time="2026-03-25T12:00:00Z", sky_state=2.0,
        ))

        # Verify sky_state is set
        assert store.get("2026-03-25T12:00:00Z").sky_state == 2.0

        # Phase 1+2 refresh (new model run): temp updated, pop updated
        store.merge(TimestepData(
            time="2026-03-25T12:00:00Z", pop=10, temp=-4.0, model="hrdps",
        ))

        # sky_state must survive (not overwritten by None)
        entry = store.get("2026-03-25T12:00:00Z")
        assert entry.sky_state == 2.0
        assert entry.temp == -4.0  # updated
        assert entry.pop == 10  # updated

    def test_new_sky_state_overwrites_old(self) -> None:
        """A new sky_state value overwrites the old one."""
        store = TimestepStore()

        store.merge(TimestepData(
            time="2026-03-25T12:00:00Z", sky_state=2.0,
        ))
        store.merge(TimestepData(
            time="2026-03-25T12:00:00Z", sky_state=8.0,
        ))

        assert store.get("2026-03-25T12:00:00Z").sky_state == 8.0

    def test_no_crash_when_store_empty(self) -> None:
        """No crash when querying a nonexistent timestep."""
        store = TimestepStore()
        assert store.get("2026-03-25T12:00:00Z") is None

    def test_multiple_timesteps_independent(self) -> None:
        """sky_state for different timesteps are independent."""
        store = TimestepStore()

        store.merge(TimestepData(
            time="2026-03-25T12:00:00Z", pop=0, sky_state=2.0,
        ))
        store.merge(TimestepData(
            time="2026-03-25T13:00:00Z", pop=30,
        ))

        assert store.get("2026-03-25T12:00:00Z").sky_state == 2.0
        assert store.get("2026-03-25T13:00:00Z").sky_state is None

    def test_sky_state_preserved_across_many_merges(self) -> None:
        """sky_state survives multiple rounds of Phase 1+2 merges."""
        store = TimestepStore()

        # Initial + lazy fetch
        store.merge(TimestepData(time="2026-03-25T12:00:00Z", pop=0))
        store.merge(TimestepData(time="2026-03-25T12:00:00Z", sky_state=5.0))

        # Several refresh cycles
        for pop in [10, 20, 0, 15]:
            store.merge(TimestepData(
                time="2026-03-25T12:00:00Z", pop=pop, temp=-3.0,
            ))

        assert store.get("2026-03-25T12:00:00Z").sky_state == 5.0
