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

from datetime import date, timedelta

import pytest
from homeassistant.core import HomeAssistant

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
            return _resp({"TOTAL_PRECIPITATION": 3.2, "TOTAL_RAIN": 3.2, "TOTAL_SNOW": 0})

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
