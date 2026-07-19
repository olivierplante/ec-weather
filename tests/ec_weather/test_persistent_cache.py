"""Persistent forecast cache — a reboot restores state instead of refetching.

The coordinator persists its fetched forecast state (canonical timestep store,
outlook, precip windows, completed days, model-run stamps, day-7 backfill,
forecast range) to a per-entry HA Store. On startup it restores that state and
lets the existing model-run-aware scheduler decide whether anything actually
needs fetching, so a reboot becomes a non-event for EC.

These are the nine spec tests (specs/ec_weather/persistent-forecast-cache.md).
Every value is synthetic (repo policy).
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock

import pytest
from freezegun import freeze_time
from homeassistant.core import HomeAssistant

from ec_weather.const import STORAGE_SCHEMA_VERSION
from ec_weather.coordinator import ECWEonGCoordinator
from ec_weather.coordinator.weong_helpers import _LAYER_SUFFIXES, _weong_layer_name
from ec_weather.timestep_store import TimestepData

from .conftest import MOCK_CONFIG_DATA


def _make(hass: HomeAssistant, entry_id: str) -> ECWEonGCoordinator:
    return ECWEonGCoordinator(
        hass, MOCK_CONFIG_DATA["geomet_bbox"], entry_id=entry_id,
    )


def _utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def _base_results(timesteps, values, model="hrdps"):
    """POP+AirTemp base results, one of each per timestep (None == failed query)."""
    pop_layer = _weong_layer_name(_LAYER_SUFFIXES["precip_prob"], model)
    temp_layer = _weong_layer_name(_LAYER_SUFFIXES["air_temp"], model)
    out = []
    for ts, value in zip(timesteps, values):
        out.append((pop_layer, ts, ("2026-07-09", "day"), value))
        temp = None if value is None else -5.0
        out.append((temp_layer, ts, ("2026-07-09", "day"), temp))
    return out


# ---------------------------------------------------------------------------
# 1 — round-trip: save -> restore reproduces the persisted state
# ---------------------------------------------------------------------------

@freeze_time("2026-07-09T12:00:00Z")
async def test_round_trip_reproduces_state(hass: HomeAssistant, hass_storage):
    coord = _make(hass, "e1")
    coord._forecast_days = 14
    coord._store.merge(TimestepData(
        time="2026-07-09T12:00:00Z", temp=20.0, pop=30,
        model="hrdps", model_run="2026-07-09T06:00:00Z",
    ))
    coord._outlook = {
        "2026-07-18": {
            "date": "2026-07-18", "source": "outlook",
            "temp_low": 10, "temp_high": 22,
        },
    }
    coord._precip_windows = {
        "2026-07-12": [{"start": "2026-07-12T12:00:00Z",
                        "end": "2026-07-13T00:00:00Z", "pop": 40}],
    }
    coord._completed_days = {"2026-07-09", "2026-07-10"}
    coord._last_model_run = "2026-07-09T06:00:00Z"
    coord._last_fetch_ts = "2026-07-09T12:05:00Z"
    coord._day7_backfill = {"date": "2026-07-15", "temp_low": 8, "pop_night": 20}

    await coord._async_persist_now()

    restored = _make(hass, "e1")
    restored._forecast_days = 14
    await restored.async_restore()

    entry = restored._store.get("2026-07-09T12:00:00Z")
    assert entry is not None
    assert entry.temp == 20.0
    assert entry.pop == 30
    assert entry.model == "hrdps"
    assert entry.model_run == "2026-07-09T06:00:00Z"
    assert restored._outlook == coord._outlook
    assert restored._precip_windows == coord._precip_windows
    assert restored._completed_days == {"2026-07-09", "2026-07-10"}
    assert restored._last_model_run == "2026-07-09T06:00:00Z"
    assert restored._last_fetch_ts == "2026-07-09T12:05:00Z"
    assert restored._day7_backfill == coord._day7_backfill


# ---------------------------------------------------------------------------
# 2 — fresh-run restore skips the wave (no queries issued)
# ---------------------------------------------------------------------------

@freeze_time("2026-07-09T09:00:00Z")
async def test_fresh_run_restore_skips_wave(hass: HomeAssistant, hass_storage):
    # At 09:00Z the latest available HRDPS run is 06Z (06+2h=08 <= 09).
    saver = _make(hass, "e2")
    saver._store.merge(TimestepData(
        time="2026-07-09T12:00:00Z", temp=18.0, pop=10, model="hrdps",
    ))
    saver._last_model_run = "2026-07-09T06:00:00Z"
    saver._completed_days = {"2026-07-09"}
    saver._last_fetch_ts = "2026-07-09T08:30:00Z"
    await saver._async_persist_now()

    coord = _make(hass, "e2")
    calls: list[int] = []

    async def spy(queries, now_ts, session, semaphore):
        calls.append(len(queries))
        return [], 0, 0

    coord._execute_queries = spy

    await coord.async_restore()
    assert coord.data is not None  # sensors show restored data immediately

    result = await coord._do_update()

    assert calls == []  # zero GeoMet queries issued
    assert result is coord.data


# ---------------------------------------------------------------------------
# 3 — stale-run restore fetches normally
# ---------------------------------------------------------------------------

@freeze_time("2026-07-09T09:00:00Z")
async def test_stale_run_restore_fetches(hass: HomeAssistant, hass_storage):
    saver = _make(hass, "e3")
    saver._store.merge(TimestepData(
        time="2026-07-09T12:00:00Z", temp=18.0, pop=10, model="hrdps",
    ))
    saver._last_model_run = "2026-07-08T18:00:00Z"  # yesterday's run — stale
    saver._completed_days = {"2026-07-09"}
    await saver._async_persist_now()

    coord = _make(hass, "e3")
    calls: list[int] = []

    async def spy(queries, now_ts, session, semaphore):
        calls.append(len(queries))
        return [], 0, 0

    coord._execute_queries = spy

    await coord.async_restore()
    assert coord.needs_refresh() is True

    await coord._do_update()
    assert calls  # a stale run refetches — queries were issued


# ---------------------------------------------------------------------------
# 4 — no store file -> full fetch (first install)
# ---------------------------------------------------------------------------

async def test_no_file_full_fetch(hass: HomeAssistant, hass_storage):
    coord = _make(hass, "e4")
    await coord.async_restore()
    assert coord.data is None
    assert coord.needs_refresh() is True


# ---------------------------------------------------------------------------
# 5 — schema-version mismatch -> discard + full fetch
# ---------------------------------------------------------------------------

async def test_schema_mismatch_discarded(hass: HomeAssistant, hass_storage):
    key = "ec_weather.e5"
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {
            "schema_version": STORAGE_SCHEMA_VERSION + 999,
            "timesteps": [{"time": "2026-07-09T12:00:00Z", "temp": 5.0}],
            "completed_days": ["2026-07-09"],
            "last_model_run": "2026-07-09T06:00:00Z",
        },
    }

    coord = _make(hass, "e5")
    await coord.async_restore()

    assert coord._completed_days == set()
    assert len(coord._store) == 0
    assert coord._last_model_run is None
    assert coord.data is None
    assert coord.needs_refresh() is True


# ---------------------------------------------------------------------------
# 6 — pruning: past dates dropped on restore
# ---------------------------------------------------------------------------

@freeze_time("2026-07-09T12:00:00Z")
async def test_pruning_drops_past_dates(hass: HomeAssistant, hass_storage):
    saver = _make(hass, "e6")
    saver._store.merge(TimestepData(
        time="2026-07-05T12:00:00Z", temp=1.0, model="hrdps",
    ))  # past
    saver._store.merge(TimestepData(
        time="2026-07-09T15:00:00Z", temp=2.0, model="hrdps",
    ))  # future
    saver._completed_days = {"2026-07-05", "2026-07-09"}
    saver._precip_windows = {
        "2026-07-05": [{"pop": 10}],
        "2026-07-10": [{"pop": 20}],
    }
    await saver._async_persist_now()

    coord = _make(hass, "e6")
    await coord.async_restore()

    assert coord._store.get("2026-07-05T12:00:00Z") is None
    assert coord._store.get("2026-07-09T15:00:00Z") is not None
    assert "2026-07-05" not in coord._completed_days
    assert "2026-07-09" in coord._completed_days
    assert "2026-07-05" not in coord._precip_windows
    assert "2026-07-10" in coord._precip_windows


# ---------------------------------------------------------------------------
# 7 — partial day restored as pending, not completed
# ---------------------------------------------------------------------------

@freeze_time("2026-07-09T12:00:00Z")
async def test_partial_day_restored_pending(hass: HomeAssistant, hass_storage):
    saver = _make(hass, "e7")
    # A future day with some data but never marked complete.
    saver._store.merge(TimestepData(
        time="2026-07-11T12:00:00Z", temp=5.0, model="rdps",
    ))
    saver._completed_days = {"2026-07-09"}
    await saver._async_persist_now()

    coord = _make(hass, "e7")
    await coord.async_restore()

    assert "2026-07-11" not in coord._completed_days  # stays pending
    assert coord._store.get("2026-07-11T12:00:00Z") is not None  # partial data kept


# ---------------------------------------------------------------------------
# 8 — extended off at restore -> persisted outlook dropped
# ---------------------------------------------------------------------------

@freeze_time("2026-07-09T12:00:00Z")
async def test_extended_off_drops_outlook(hass: HomeAssistant, hass_storage):
    saver = _make(hass, "e8")
    saver._forecast_days = 14
    saver._outlook = {
        "2026-07-18": {
            "date": "2026-07-18", "source": "outlook",
            "temp_low": 10, "temp_high": 22,
        },
    }
    saver._day7_backfill = {"date": "2026-07-15", "temp_low": 8, "pop_night": 20}
    await saver._async_persist_now()

    coord = _make(hass, "e8")  # default forecast_days == 7 (extended off)
    await coord.async_restore()

    assert coord._outlook == {}
    assert coord._day7_backfill is None


# ---------------------------------------------------------------------------
# 9 — failures still never persisted (resilience carried through a cycle)
# ---------------------------------------------------------------------------

@freeze_time("2026-07-09T12:00:00Z")
async def test_failures_not_persisted(hass: HomeAssistant, hass_storage):
    coord = _make(hass, "e9")
    date_str = "2026-07-09"
    day_periods = [(date_str, "day", _utc(2026, 7, 9, 12), _utc(2026, 7, 9, 22))]
    today = date(2026, 7, 9)

    async def mock_fetch_day(dp, td, now_ts, session, sem):
        steps = [_utc(2026, 7, 9, 12 + i) for i in range(10)]
        values = [10.0, 20.0] + [None] * 8  # 2 good, 8 failed
        return _base_results(steps, values)

    async def mock_geps(*args):
        return [], None

    coord._fetch_day = mock_fetch_day
    coord._fetch_geps_day = mock_geps

    semaphore = asyncio.Semaphore(1)
    await coord._process_day(
        date_str, day_periods, today, 0.0, None, semaphore, day_periods,
    )
    assert date_str not in coord._completed_days  # partial -> pending

    await coord._async_persist_now()

    restored = _make(hass, "e9")
    await restored.async_restore()

    assert date_str not in restored._completed_days
    # The two good timesteps survive; the failed ones were never stored.
    assert restored._store.get("2026-07-09T12:00:00Z") is not None
    assert restored._store.get("2026-07-09T13:00:00Z") is not None
    assert restored._store.get("2026-07-09T14:00:00Z") is None


# ---------------------------------------------------------------------------
# 10 — malformed / partial on-disk payloads: restore-or-discard, never crash
#      (schema drift after an upgrade; corrupt writes). Test 5 covered a
#      schema-version MISMATCH; these cover an unreadable file, an absent
#      schema_version, and a schema-current-but-fieldless payload.
# ---------------------------------------------------------------------------

async def test_unreadable_file_discarded_no_crash(hass: HomeAssistant, hass_storage):
    """async_load raising (corrupt on-disk JSON) is caught → fresh fetch, no crash."""
    coord = _make(hass, "e10")
    assert coord._persist_store is not None
    coord._persist_store.async_load = AsyncMock(side_effect=ValueError("corrupt json"))

    await coord.async_restore()  # must not raise

    assert coord.data is None
    assert len(coord._store) == 0
    assert coord._completed_days == set()
    assert coord.needs_refresh() is True


async def test_absent_schema_version_discarded(hass: HomeAssistant, hass_storage):
    """A payload with NO schema_version key is a mismatch (None != current) —
    discarded, never migrated by guess."""
    key = "ec_weather.e11"
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {  # schema_version deliberately absent
            "timesteps": [{"time": "2026-07-09T12:00:00Z", "temp": 5.0}],
            "completed_days": ["2026-07-09"],
            "last_model_run": "2026-07-09T06:00:00Z",
        },
    }

    coord = _make(hass, "e11")
    await coord.async_restore()

    assert len(coord._store) == 0
    assert coord._completed_days == set()
    assert coord._last_model_run is None
    assert coord.data is None
    assert coord.needs_refresh() is True


@freeze_time("2026-07-09T12:00:00Z")
async def test_schema_current_but_fieldless_payload_restores_clean(
    hass: HomeAssistant, hass_storage,
):
    """A schema-current payload missing every optional field restores to a safe
    empty state and projects without crashing (each field defaults via .get)."""
    key = "ec_weather.e12"
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {"schema_version": STORAGE_SCHEMA_VERSION},  # nothing else
    }

    coord = _make(hass, "e12")
    coord._forecast_days = 14  # extended on — exercises the outlook branch too
    await coord.async_restore()  # must not raise

    assert len(coord._store) == 0
    assert coord._completed_days == set()
    assert coord._precip_windows == {}
    assert coord._outlook == {}
    assert coord._day7_backfill is None
    assert coord._last_model_run is None
