"""Tests for yesterday's precipitation parsing (issue #9, Part B).

EC ``climate-daily`` collection. Verified data facts (live probe, June 2026):

- Split-capable stations report TOTAL_RAIN (mm), TOTAL_SNOW (cm),
  TOTAL_PRECIPITATION (mm water-equiv). Absent type = 0, never null.
- Combined-only stations report only TOTAL_PRECIPITATION; rain/snow always null.
- Unpublished day: either the feature row is absent (features=[]) OR the row
  exists with TOTAL_PRECIPITATION = null. Both mean "not published yet".
- Published dry day: TOTAL_PRECIPITATION = 0 (split: rain=0, snow=0 too).

The parser turns this into a uniform shape the sensors/card consume.
``null`` (unpublished) and ``0`` (measured-dry) must never be conflated.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from ec_weather.const import (
    CONF_LAT,
    CONF_LON,
    CONF_PRECIP_STATION_DISTANCE_KM,
    CONF_PRECIP_STATION_ID,
    CONF_PRECIP_STATION_NAME,
    CONF_PRECIP_STATION_TYPE,
)
from ec_weather.coordinator.climate import (
    ECClimateCoordinator,
    parse_climate_response,
)


def _resp(props: dict | None) -> dict:
    """Wrap properties in a GeoJSON FeatureCollection, or empty when None."""
    if props is None:
        return {"features": []}
    return {"features": [{"properties": props}]}


class TestUnpublished:
    def test_empty_features_is_unpublished(self):
        """No row for yesterday → not published."""
        result = parse_climate_response(_resp(None), station_type="split")
        assert result["published"] is False
        assert result["total_mm"] is None
        assert result["rain_mm"] is None
        assert result["snow_cm"] is None

    def test_row_present_but_total_null_is_unpublished(self):
        """Row exists but TOTAL_PRECIPITATION null → not published (day in progress)."""
        props = {"TOTAL_PRECIPITATION": None, "TOTAL_RAIN": None, "TOTAL_SNOW": None}
        result = parse_climate_response(_resp(props), station_type="split")
        assert result["published"] is False

    def test_combined_unpublished_ignores_null_rain_snow(self):
        """Combined station: only total drives published; rain/snow always null."""
        props = {"TOTAL_PRECIPITATION": None, "TOTAL_RAIN": None, "TOTAL_SNOW": None}
        result = parse_climate_response(_resp(props), station_type="combined")
        assert result["published"] is False


class TestPublishedDry:
    def test_split_dry_day_is_published_with_zeros(self):
        """Split station dry day: total=0, rain=0, snow=0 → published, real zeros."""
        props = {"TOTAL_PRECIPITATION": 0, "TOTAL_RAIN": 0, "TOTAL_SNOW": 0}
        result = parse_climate_response(_resp(props), station_type="split")
        assert result["published"] is True
        assert result["total_mm"] == 0
        assert result["rain_mm"] == 0
        assert result["snow_cm"] == 0

    def test_combined_dry_day_is_published(self):
        """Combined station dry day: total=0 → published; rain/snow stay None."""
        props = {"TOTAL_PRECIPITATION": 0, "TOTAL_RAIN": None, "TOTAL_SNOW": None}
        result = parse_climate_response(_resp(props), station_type="combined")
        assert result["published"] is True
        assert result["total_mm"] == 0
        assert result["rain_mm"] is None
        assert result["snow_cm"] is None


class TestPublishedWet:
    def test_split_rain_only(self):
        props = {"TOTAL_PRECIPITATION": 12.4, "TOTAL_RAIN": 12.4, "TOTAL_SNOW": 0}
        result = parse_climate_response(_resp(props), station_type="split")
        assert result["published"] is True
        assert result["rain_mm"] == 12.4
        assert result["snow_cm"] == 0

    def test_split_snow_only(self):
        """Snow in cm, water-equiv total in mm — different units, both kept."""
        props = {"TOTAL_PRECIPITATION": 5.8, "TOTAL_RAIN": 0, "TOTAL_SNOW": 6.2}
        result = parse_climate_response(_resp(props), station_type="split")
        assert result["rain_mm"] == 0
        assert result["snow_cm"] == 6.2
        assert result["total_mm"] == 5.8

    def test_split_mixed_day(self):
        """A single winter day can have both rain and snow."""
        props = {"TOTAL_PRECIPITATION": 8.4, "TOTAL_RAIN": 2.2, "TOTAL_SNOW": 6.2}
        result = parse_climate_response(_resp(props), station_type="split")
        assert result["rain_mm"] == 2.2
        assert result["snow_cm"] == 6.2

    def test_combined_wet_day_has_no_split(self):
        """Combined station never fabricates rain/snow even when wet."""
        props = {"TOTAL_PRECIPITATION": 8.6, "TOTAL_RAIN": None, "TOTAL_SNOW": None}
        result = parse_climate_response(_resp(props), station_type="combined")
        assert result["published"] is True
        assert result["total_mm"] == 8.6
        assert result["rain_mm"] is None
        assert result["snow_cm"] is None


class TestStationType:
    def test_station_type_echoed_in_result(self):
        """Result reports the station type so consumers can branch display."""
        props = {"TOTAL_PRECIPITATION": 0, "TOTAL_RAIN": 0, "TOTAL_SNOW": 0}
        assert parse_climate_response(_resp(props), station_type="split")["station_type"] == "split"
        assert parse_climate_response(_resp(props), station_type="combined")["station_type"] == "combined"


class TestCoordinator:
    """Stateful behavior: unconfigured short-circuit and re-fetch caching."""

    async def test_unconfigured_returns_unavailable_without_fetch(
        self, hass: HomeAssistant
    ) -> None:
        """No station → available=False, no network call."""
        coord = ECClimateCoordinator(hass, station_id=None)
        result = await coord._do_update()
        assert result["available"] is False
        assert result["published"] is False

    async def test_unconfigured_is_not_polling(self, hass: HomeAssistant) -> None:
        """An unconfigured coordinator must not schedule polling."""
        coord = ECClimateCoordinator(hass, station_id=None)
        assert coord.update_interval is None

    async def test_skips_refetch_when_yesterday_already_published(
        self, hass: HomeAssistant, monkeypatch
    ) -> None:
        """Once yesterday is published, a second update returns cached data."""
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        calls = {"n": 0}

        async def fake_fetch(session, url, **kwargs):
            calls["n"] += 1
            # The coordinator now queries a lookback window (not just
            # yesterday) and selects the row by LOCAL_DATE == yesterday, so
            # the fixture must carry it — a real EC response always does
            # since the coordinator's URL requests the LOCAL_DATE property.
            return _resp({
                "LOCAL_DATE": yesterday,
                "TOTAL_PRECIPITATION": 3.2,
                "TOTAL_RAIN": 3.2,
                "TOTAL_SNOW": 0,
            })

        monkeypatch.setattr(
            "ec_weather.coordinator.climate.fetch_json_with_retry", fake_fetch
        )
        coord = ECClimateCoordinator(
            hass, station_id="7025251", station_type="split"
        )

        first = await coord._do_update()
        assert first["published"] is True
        assert coord._published_date == yesterday

        coord.data = first
        second = await coord._do_update()
        assert calls["n"] == 1, "Should not re-fetch once yesterday is published"
        assert second is first

    async def test_retries_when_not_yet_published(
        self, hass: HomeAssistant, monkeypatch
    ) -> None:
        """An unpublished (null total) response does not get cached as final."""
        async def fake_fetch(session, url, **kwargs):
            return _resp({"TOTAL_PRECIPITATION": None})

        monkeypatch.setattr(
            "ec_weather.coordinator.climate.fetch_json_with_retry", fake_fetch
        )
        coord = ECClimateCoordinator(
            hass, station_id="7025251", station_type="combined"
        )
        result = await coord._do_update()
        assert result["published"] is False
        assert coord._published_date is None


class TestSelfHeal:
    """Self-heal a lagging precip station (issue #9 continuation, mirrors
    ECAQHICoordinator._maybe_rediscover_station): at most one rediscovery
    attempt per 24h, adopt only a STRICTLY fresher candidate, persist to the
    config entry in place (no reload wired for this integration)."""

    STATION_ID = "1234567"
    LAT, LON = 45.5017, -73.5673

    def _make_entry(
        self, station_type="combined", station_name="TestStation", distance_km=24.6
    ) -> MagicMock:
        entry = MagicMock()
        entry.entry_id = "test_entry"
        entry.data = {
            CONF_LAT: self.LAT,
            CONF_LON: self.LON,
            CONF_PRECIP_STATION_ID: self.STATION_ID,
            CONF_PRECIP_STATION_TYPE: station_type,
            CONF_PRECIP_STATION_NAME: station_name,
            CONF_PRECIP_STATION_DISTANCE_KM: distance_km,
        }
        entry.options = {}
        return entry

    def _window_resp(self, rows: list[tuple[str, float | None]]) -> dict:
        """rows: list of (LOCAL_DATE iso string, TOTAL_PRECIPITATION or None)."""
        return {
            "features": [
                {
                    "properties": {
                        "LOCAL_DATE": local_date,
                        "TOTAL_PRECIPITATION": total,
                        "TOTAL_RAIN": None,
                        "TOTAL_SNOW": None,
                    }
                }
                for local_date, total in rows
            ]
        }

    def _candidate(
        self, station_id, station_type, name, distance_km, latest_precip_date
    ) -> dict:
        return {
            "station_id": station_id,
            "name": name,
            "type": station_type,
            "distance_km": distance_km,
            "lat": self.LAT,
            "lon": self.LON,
            "latest_precip_date": latest_precip_date,
        }

    @pytest.fixture(autouse=True)
    def _patch_session(self):
        """Prevent any real client-session lookup during these unit tests."""
        with patch(
            "ec_weather.coordinator.climate.async_get_clientsession",
            return_value=MagicMock(),
        ):
            yield

    async def test_stale_for_4_days_triggers_discovery_and_adopts_fresher_candidate(
        self, hass: HomeAssistant
    ) -> None:
        """A station whose most recently published value is 4 days old
        triggers exactly one discovery call and adopts+persists a candidate
        whose latest_precip_date is strictly newer."""
        entry = self._make_entry()
        coord = ECClimateCoordinator(
            hass,
            station_id=self.STATION_ID,
            station_type="combined",
            station_name="TestStation",
            distance_km=24.6,
            entry=entry,
        )
        hass.config_entries.async_update_entry = MagicMock()

        stale_date = (date.today() - timedelta(days=4)).isoformat()
        fresh_date = (date.today() - timedelta(days=1)).isoformat()
        candidate = self._candidate(
            "7654321", "combined", "TestReplacement", 12.0, fresh_date
        )

        with patch(
            "ec_weather.coordinator.climate.fetch_json_with_retry",
            AsyncMock(return_value=self._window_resp([(stale_date, 2.0)])),
        ), patch(
            "ec_weather.coordinator.climate.discover_precip_stations",
            AsyncMock(return_value={"nearest": candidate, "nearest_split": None}),
        ) as mock_discover:
            await coord._do_update()

        mock_discover.assert_awaited_once()
        assert coord.station_id == "7654321"
        assert coord.station_name == "TestReplacement"
        assert coord.distance_km == 12.0
        hass.config_entries.async_update_entry.assert_called_once()
        call = hass.config_entries.async_update_entry.call_args
        assert call.args[0] is entry
        assert call.kwargs["data"][CONF_PRECIP_STATION_ID] == "7654321"
        assert call.kwargs["data"][CONF_PRECIP_STATION_NAME] == "TestReplacement"
        assert call.kwargs["data"][CONF_PRECIP_STATION_DISTANCE_KM] == 12.0

    async def test_equal_or_older_candidate_does_not_adopt(
        self, hass: HomeAssistant
    ) -> None:
        """A candidate whose latest_precip_date is equal to (or older than)
        the current station's is not an improvement — must not be adopted."""
        entry = self._make_entry()
        coord = ECClimateCoordinator(
            hass,
            station_id=self.STATION_ID,
            station_type="combined",
            station_name="TestStation",
            distance_km=24.6,
            entry=entry,
        )
        hass.config_entries.async_update_entry = MagicMock()

        stale_date = (date.today() - timedelta(days=4)).isoformat()
        candidate = self._candidate(
            "7654321", "combined", "TestReplacement", 12.0, stale_date
        )

        with patch(
            "ec_weather.coordinator.climate.fetch_json_with_retry",
            AsyncMock(return_value=self._window_resp([(stale_date, 2.0)])),
        ), patch(
            "ec_weather.coordinator.climate.discover_precip_stations",
            AsyncMock(return_value={"nearest": candidate, "nearest_split": None}),
        ):
            await coord._do_update()

        assert coord.station_id == self.STATION_ID
        hass.config_entries.async_update_entry.assert_not_called()

    async def test_rate_limit_blocks_second_attempt_within_24h(
        self, hass: HomeAssistant
    ) -> None:
        """Two stale polls inside the 24h window yield only one discovery
        query — same rate limit as ECAQHICoordinator."""
        entry = self._make_entry()
        coord = ECClimateCoordinator(
            hass,
            station_id=self.STATION_ID,
            station_type="combined",
            station_name="TestStation",
            distance_km=24.6,
            entry=entry,
        )
        hass.config_entries.async_update_entry = MagicMock()

        stale_date = (date.today() - timedelta(days=5)).isoformat()
        base = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)

        with patch(
            "ec_weather.coordinator.climate.fetch_json_with_retry",
            AsyncMock(return_value=self._window_resp([(stale_date, 2.0)])),
        ), patch(
            "ec_weather.coordinator.climate.discover_precip_stations",
            AsyncMock(return_value={"nearest": None, "nearest_split": None}),
        ) as mock_discover, patch(
            "ec_weather.coordinator.climate.dt_util.utcnow"
        ) as mock_now:
            mock_now.return_value = base
            await coord._do_update()
            mock_now.return_value = base + timedelta(hours=6)
            await coord._do_update()

        assert mock_discover.await_count == 1

    async def test_healthy_station_never_calls_discovery(
        self, hass: HomeAssistant
    ) -> None:
        """A station whose latest published value is well within the
        freshness threshold never triggers a discovery call."""
        entry = self._make_entry()
        coord = ECClimateCoordinator(
            hass,
            station_id=self.STATION_ID,
            station_type="combined",
            station_name="TestStation",
            distance_km=24.6,
            entry=entry,
        )
        hass.config_entries.async_update_entry = MagicMock()

        fresh_date = (date.today() - timedelta(days=2)).isoformat()

        with patch(
            "ec_weather.coordinator.climate.fetch_json_with_retry",
            AsyncMock(return_value=self._window_resp([(fresh_date, 2.0)])),
        ), patch(
            "ec_weather.coordinator.climate.discover_precip_stations",
        ) as mock_discover:
            await coord._do_update()

        mock_discover.assert_not_called()

    async def test_split_station_type_requests_nearest_split_candidate(
        self, hass: HomeAssistant
    ) -> None:
        """A split-capable install must be replaced by the nearest FRESH
        split-capable candidate (nearest_split), not the plain 'nearest'
        pick, and adopts the candidate's own station_type."""
        entry = self._make_entry(station_type="split")
        coord = ECClimateCoordinator(
            hass,
            station_id=self.STATION_ID,
            station_type="split",
            station_name="TestStation",
            distance_km=24.6,
            entry=entry,
        )
        hass.config_entries.async_update_entry = MagicMock()

        stale_date = (date.today() - timedelta(days=4)).isoformat()
        fresh_date = (date.today() - timedelta(days=1)).isoformat()
        split_candidate = self._candidate(
            "SPLIT99", "split", "TestSplitReplacement", 30.0, fresh_date
        )

        with patch(
            "ec_weather.coordinator.climate.fetch_json_with_retry",
            AsyncMock(return_value=self._window_resp([(stale_date, 2.0)])),
        ), patch(
            "ec_weather.coordinator.climate.discover_precip_stations",
            AsyncMock(
                return_value={"nearest": None, "nearest_split": split_candidate}
            ),
        ):
            await coord._do_update()

        assert coord.station_id == "SPLIT99"
        assert coord.station_type == "split"

    async def test_no_entry_never_calls_discovery(self, hass: HomeAssistant) -> None:
        """Without a config entry (unit-constructed coordinator), a stale
        station never attempts rediscovery — there is nowhere to persist a
        replacement and no lat/lon to search around."""
        coord = ECClimateCoordinator(
            hass,
            station_id=self.STATION_ID,
            station_type="combined",
            station_name="TestStation",
            distance_km=24.6,
        )

        stale_date = (date.today() - timedelta(days=5)).isoformat()

        with patch(
            "ec_weather.coordinator.climate.fetch_json_with_retry",
            AsyncMock(return_value=self._window_resp([(stale_date, 2.0)])),
        ), patch(
            "ec_weather.coordinator.climate.discover_precip_stations",
        ) as mock_discover:
            await coord._do_update()

        mock_discover.assert_not_called()
