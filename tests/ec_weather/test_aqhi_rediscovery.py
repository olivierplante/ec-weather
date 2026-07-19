"""AQHI station self-healing re-discovery (issue #12, second reporter).

When a configured AQHI station id retires or EC renumbers it, the
``aqhi-forecasts-realtime`` collection keeps returning a well-formed
response with zero features. The coordinator must re-run the existing
station discovery, at most once per 24h, and adopt a different station
if one is found near the city — without adding a polling storm.

These tests drive ``ECAQHICoordinator._do_update`` directly, mocking the
network fetch and the discovery helper. Time is controlled via the
coordinator module's ``dt_util.utcnow`` so the 24h rate-limit is testable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from ec_weather.const import CONF_AQHI_LOCATION_ID, CONF_LAT, CONF_LON
from ec_weather.coordinator import ECAQHICoordinator

# A public city (Ottawa) — never real personal coordinates.
_LAT = 45.42
_LON = -75.70
_DEAD_STATION = "15026"


def _make_entry(location_id: str | None = _DEAD_STATION) -> MagicMock:
    """A minimal config-entry double carrying lat/lon and the station id."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {
        CONF_LAT: _LAT,
        CONF_LON: _LON,
        CONF_AQHI_LOCATION_ID: location_id,
    }
    entry.options = {}
    return entry


def _make_coordinator(
    hass: HomeAssistant,
    location_id: str | None = _DEAD_STATION,
    entry: MagicMock | None = None,
) -> ECAQHICoordinator:
    coord = ECAQHICoordinator(
        hass,
        location_id,
        polling=False,
        entry=entry if entry is not None else _make_entry(location_id),
    )
    return coord


def _empty_response() -> dict:
    """A well-formed EC response with an empty features list."""
    return {"type": "FeatureCollection", "features": []}


@pytest.fixture(autouse=True)
def _patch_session():
    """Prevent any real client-session lookup during these unit tests."""
    with patch(
        "ec_weather.coordinator.aqhi.async_get_clientsession",
        return_value=MagicMock(),
    ):
        yield


class TestRediscoveryTrigger:
    async def test_empty_response_triggers_one_discovery(
        self, hass: HomeAssistant
    ) -> None:
        """A well-formed empty response with a configured station re-discovers once."""
        coord = _make_coordinator(hass)

        with patch(
            "ec_weather.coordinator.aqhi.fetch_json_with_retry",
            AsyncMock(return_value=_empty_response()),
        ), patch(
            "ec_weather.coordinator.aqhi.discover_aqhi_station",
            AsyncMock(return_value=None),
        ) as mock_discover:
            await coord._do_update()

        mock_discover.assert_awaited_once()
        # Discovery must be called with the entry's lat/lon.
        assert mock_discover.await_args.kwargs.get("lat") == _LAT
        assert mock_discover.await_args.kwargs.get("lon") == _LON

    async def test_second_empty_within_24h_does_not_rediscover(
        self, hass: HomeAssistant
    ) -> None:
        """Two dead polls inside the 24h window yield only one discovery query."""
        coord = _make_coordinator(hass)
        base = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)

        with patch(
            "ec_weather.coordinator.aqhi.fetch_json_with_retry",
            AsyncMock(return_value=_empty_response()),
        ), patch(
            "ec_weather.coordinator.aqhi.discover_aqhi_station",
            AsyncMock(return_value=None),
        ) as mock_discover, patch(
            "ec_weather.coordinator.aqhi.dt_util.utcnow"
        ) as mock_now:
            mock_now.return_value = base
            await coord._do_update()
            # 6 hours later — still inside the window.
            mock_now.return_value = base + timedelta(hours=6)
            await coord._do_update()

        assert mock_discover.await_count == 1

    async def test_empty_after_24h_rediscovers_again(
        self, hass: HomeAssistant
    ) -> None:
        """Once the window elapses, a still-dead station re-discovers again."""
        coord = _make_coordinator(hass)
        base = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)

        with patch(
            "ec_weather.coordinator.aqhi.fetch_json_with_retry",
            AsyncMock(return_value=_empty_response()),
        ), patch(
            "ec_weather.coordinator.aqhi.discover_aqhi_station",
            AsyncMock(return_value=None),
        ) as mock_discover, patch(
            "ec_weather.coordinator.aqhi.dt_util.utcnow"
        ) as mock_now:
            mock_now.return_value = base
            await coord._do_update()
            # 25 hours later — window has elapsed.
            mock_now.return_value = base + timedelta(hours=25)
            await coord._do_update()

        assert mock_discover.await_count == 2

    async def test_fetch_failure_does_not_rediscover(
        self, hass: HomeAssistant
    ) -> None:
        """An exception from the fetch must never trigger discovery."""
        coord = _make_coordinator(hass)

        with patch(
            "ec_weather.coordinator.aqhi.fetch_json_with_retry",
            AsyncMock(side_effect=RuntimeError("boom")),
        ), patch(
            "ec_weather.coordinator.aqhi.discover_aqhi_station",
            AsyncMock(return_value="99999"),
        ) as mock_discover:
            with pytest.raises(RuntimeError):
                await coord._do_update()

        mock_discover.assert_not_awaited()

    async def test_malformed_features_does_not_rediscover(
        self, hass: HomeAssistant
    ) -> None:
        """A body whose ``features`` is not a list is malformed, not empty."""
        coord = _make_coordinator(hass)

        with patch(
            "ec_weather.coordinator.aqhi.fetch_json_with_retry",
            AsyncMock(return_value={"features": "not-a-list"}),
        ), patch(
            "ec_weather.coordinator.aqhi.discover_aqhi_station",
            AsyncMock(return_value="99999"),
        ) as mock_discover:
            await coord._do_update()

        mock_discover.assert_not_awaited()

    async def test_no_configured_station_never_rediscovers(
        self, hass: HomeAssistant
    ) -> None:
        """With no station configured, the update short-circuits before any fetch."""
        coord = _make_coordinator(hass, location_id=None, entry=_make_entry(None))

        with patch(
            "ec_weather.coordinator.aqhi.fetch_json_with_retry",
            AsyncMock(return_value=_empty_response()),
        ) as mock_fetch, patch(
            "ec_weather.coordinator.aqhi.discover_aqhi_station",
            AsyncMock(return_value="99999"),
        ) as mock_discover:
            await coord._do_update()

        mock_fetch.assert_not_awaited()
        mock_discover.assert_not_awaited()


class TestRediscoveryOutcome:
    async def test_different_station_updates_entry_and_logs_info(
        self, hass: HomeAssistant, caplog
    ) -> None:
        """A new station id updates the config entry and logs one INFO line."""
        entry = _make_entry()
        coord = _make_coordinator(hass, entry=entry)
        hass.config_entries.async_update_entry = MagicMock()

        with patch(
            "ec_weather.coordinator.aqhi.fetch_json_with_retry",
            AsyncMock(return_value=_empty_response()),
        ), patch(
            "ec_weather.coordinator.aqhi.discover_aqhi_station",
            AsyncMock(return_value="FEBWC"),
        ), caplog.at_level("INFO"):
            await coord._do_update()

        hass.config_entries.async_update_entry.assert_called_once()
        call = hass.config_entries.async_update_entry.call_args
        assert call.args[0] is entry
        assert call.kwargs["data"][CONF_AQHI_LOCATION_ID] == "FEBWC"
        # Coordinator adopts the new station in place (no reload wired).
        assert coord.aqhi_location_id == "FEBWC"
        # Exactly one INFO line naming old and new station.
        info_lines = [
            r for r in caplog.records
            if r.levelname == "INFO" and "FEBWC" in r.getMessage()
        ]
        assert len(info_lines) == 1
        assert _DEAD_STATION in info_lines[0].getMessage()

    async def test_discovery_none_leaves_entry_untouched(
        self, hass: HomeAssistant, caplog
    ) -> None:
        """Discovery returning None → no entry update, no INFO line."""
        entry = _make_entry()
        coord = _make_coordinator(hass, entry=entry)
        hass.config_entries.async_update_entry = MagicMock()

        with patch(
            "ec_weather.coordinator.aqhi.fetch_json_with_retry",
            AsyncMock(return_value=_empty_response()),
        ), patch(
            "ec_weather.coordinator.aqhi.discover_aqhi_station",
            AsyncMock(return_value=None),
        ), caplog.at_level("INFO"):
            await coord._do_update()

        hass.config_entries.async_update_entry.assert_not_called()
        assert coord.aqhi_location_id == _DEAD_STATION
        info_lines = [r for r in caplog.records if r.levelname == "INFO"]
        assert info_lines == []

    async def test_same_station_leaves_entry_untouched(
        self, hass: HomeAssistant
    ) -> None:
        """Discovery returning the same id → no entry update."""
        entry = _make_entry()
        coord = _make_coordinator(hass, entry=entry)
        hass.config_entries.async_update_entry = MagicMock()

        with patch(
            "ec_weather.coordinator.aqhi.fetch_json_with_retry",
            AsyncMock(return_value=_empty_response()),
        ), patch(
            "ec_weather.coordinator.aqhi.discover_aqhi_station",
            AsyncMock(return_value=_DEAD_STATION),
        ):
            await coord._do_update()

        hass.config_entries.async_update_entry.assert_not_called()
        assert coord.aqhi_location_id == _DEAD_STATION


def _live_response(aqhi: float = 3) -> dict:
    """A well-formed response carrying one future forecast the parser accepts."""
    return {
        "type": "FeatureCollection",
        "features": [{
            "properties": {
                "aqhi": aqhi,
                # Far-future so it always clears the current-hour filter.
                "forecast_datetime": "2100-01-01T00:00:00Z",
                "publication_datetime": "2100-01-01T00:00:00Z",
            },
        }],
    }


class TestRediscoveryRefreshInterleave:
    """A normal refresh (and a station swap) interleaved between dead polls must
    not disturb the in-memory 24h re-discovery rate-limit — the untested race
    the existing single-poll tests don't cover."""

    async def test_live_refresh_and_swap_between_dead_polls_keep_rate_limit(
        self, hass: HomeAssistant,
    ) -> None:
        """dead → adopt new station → LIVE refresh → new station dies < 24h:
        the clock survived the success AND the swap, so no second discovery."""
        entry = _make_entry()
        coord = _make_coordinator(hass, entry=entry)
        hass.config_entries.async_update_entry = MagicMock()
        coord.is_fresh = lambda: False  # force every _do_update to fetch

        base = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)

        with patch(
            "ec_weather.coordinator.aqhi.fetch_json_with_retry", AsyncMock(),
        ) as mock_fetch, patch(
            "ec_weather.coordinator.aqhi.discover_aqhi_station",
            AsyncMock(return_value="FEBWC"),
        ) as mock_discover, patch(
            "ec_weather.coordinator.aqhi.dt_util.utcnow",
        ) as mock_now:
            # 1) dead poll → rediscover + adopt the new station.
            mock_now.return_value = base
            mock_fetch.return_value = _empty_response()
            await coord._do_update()
            assert coord.aqhi_location_id == "FEBWC"
            assert mock_discover.await_count == 1

            # 2) interleaved LIVE refresh on the new station — no rediscovery.
            mock_now.return_value = base + timedelta(hours=1)
            mock_fetch.return_value = _live_response(3)
            result = await coord._do_update()
            assert result["aqhi"] == 3
            assert mock_discover.await_count == 1

            # 3) the new station also dies, still inside 24h → rate-limited.
            mock_now.return_value = base + timedelta(hours=2)
            mock_fetch.return_value = _empty_response()
            await coord._do_update()
            assert mock_discover.await_count == 1

    async def test_adopted_station_dead_after_window_rediscovers_again(
        self, hass: HomeAssistant,
    ) -> None:
        """The rate-limit is per-clock, not per-station: once 24h elapse, the
        adopted-but-now-dead station re-discovers a second replacement."""
        entry = _make_entry()
        coord = _make_coordinator(hass, entry=entry)
        hass.config_entries.async_update_entry = MagicMock()
        coord.is_fresh = lambda: False

        base = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)

        with patch(
            "ec_weather.coordinator.aqhi.fetch_json_with_retry",
            AsyncMock(return_value=_empty_response()),
        ), patch(
            "ec_weather.coordinator.aqhi.discover_aqhi_station",
            AsyncMock(side_effect=["FEBWC", "GHIJK"]),
        ) as mock_discover, patch(
            "ec_weather.coordinator.aqhi.dt_util.utcnow",
        ) as mock_now:
            mock_now.return_value = base
            await coord._do_update()
            assert coord.aqhi_location_id == "FEBWC"

            # Interleaved LIVE refresh mid-window must not consume the window.
            mock_now.return_value = base + timedelta(hours=6)
            await coord._do_update()  # still dead in this test — rate-limited
            assert mock_discover.await_count == 1

            # 25h after the first attempt → window elapsed, adopt a second id.
            mock_now.return_value = base + timedelta(hours=25)
            await coord._do_update()
            assert mock_discover.await_count == 2
            assert coord.aqhi_location_id == "GHIJK"
