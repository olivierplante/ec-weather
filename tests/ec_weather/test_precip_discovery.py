"""Tests for nearest precipitation-station discovery (issue #9, Part B).

EC ``climate-daily`` is mostly a dead historical archive — most stations in
any bbox report null precipitation. Discovery must pick the nearest station
that *actually* reports precipitation (non-null TOTAL_PRECIPITATION over a
recent window), and separately surface the nearest station that reports the
rain/snow split (non-null TOTAL_RAIN on any day in the window).

``parse_precip_stations`` is the pure aggregator over a windowed API response.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ec_weather.api_client import discover_precip_stations, parse_precip_stations


def _feature(station_id, name, lat, lon, total, rain=None, snow=None, local_date=None):
    props = {
        "CLIMATE_IDENTIFIER": station_id,
        "STATION_NAME": name,
        "TOTAL_PRECIPITATION": total,
        "TOTAL_RAIN": rain,
        "TOTAL_SNOW": snow,
    }
    if local_date is not None:
        # Only set when a test cares about freshness — omitting it (as the
        # pre-freshness tests do) matches a row with no LOCAL_DATE property.
        props["LOCAL_DATE"] = local_date
    return {
        "geometry": {"coordinates": [lon, lat]},
        "properties": props,
    }


def _resp(features):
    return {"features": features}


# Reference point — public coords (Saint-Jérôme-ish, synthetic).
LAT, LON = 45.78, -74.00


class TestNearestReporting:
    def test_skips_dead_stations_with_null_precip(self):
        """A geographically nearest station with null precip is ignored."""
        data = _resp([
            _feature("DEAD", "Dead Close", 45.79, -74.01, total=None),
            _feature("ALIVE", "Alive Far", 45.47, -73.74, total=0),
        ])
        result = parse_precip_stations(data, LAT, LON)
        assert result["nearest"]["station_id"] == "ALIVE"

    def test_picks_closest_among_reporting(self):
        """Among reporting stations, the closest wins."""
        data = _resp([
            _feature("FAR", "Far", 45.10, -73.50, total=2.0),
            _feature("NEAR", "Near", 45.70, -74.05, total=2.0),
        ])
        result = parse_precip_stations(data, LAT, LON)
        assert result["nearest"]["station_id"] == "NEAR"

    def test_dry_day_zero_counts_as_reporting(self):
        """total=0 is a real measurement → station counts as reporting."""
        data = _resp([_feature("DRY", "Dry", 45.70, -74.05, total=0)])
        result = parse_precip_stations(data, LAT, LON)
        assert result["nearest"]["station_id"] == "DRY"

    def test_no_reporting_station_returns_none(self):
        """All-null bbox → nearest is None (feature simply unavailable)."""
        data = _resp([_feature("X", "X", 45.7, -74.0, total=None)])
        result = parse_precip_stations(data, LAT, LON)
        assert result["nearest"] is None
        assert result["nearest_split"] is None

    def test_empty_response(self):
        result = parse_precip_stations(_resp([]), LAT, LON)
        assert result["nearest"] is None
        assert result["nearest_split"] is None


class TestStationType:
    def test_combined_station_typed_combined(self):
        """Reporting but no rain split → type 'combined'."""
        data = _resp([_feature("C", "Combined", 45.7, -74.0, total=5.0, rain=None)])
        result = parse_precip_stations(data, LAT, LON)
        assert result["nearest"]["type"] == "combined"

    def test_split_station_typed_split(self):
        """Non-null rain → type 'split'."""
        data = _resp([_feature("S", "Split", 45.7, -74.0, total=5.0, rain=5.0, snow=0)])
        result = parse_precip_stations(data, LAT, LON)
        assert result["nearest"]["type"] == "split"

    def test_split_detected_across_window_rows(self):
        """A station is split if ANY day in the window has non-null rain."""
        data = _resp([
            _feature("S", "Split", 45.7, -74.0, total=0, rain=None),   # dry-gap day
            _feature("S", "Split", 45.7, -74.0, total=4.0, rain=4.0),  # rainy day
        ])
        result = parse_precip_stations(data, LAT, LON)
        assert result["nearest"]["type"] == "split"


class TestNearestSplit:
    def test_nearest_split_when_nearest_is_combined(self):
        """When the nearest reporting station is combined-only, surface the
        nearest split-capable station separately."""
        data = _resp([
            _feature("COMBO", "Combo Near", 45.75, -74.02, total=3.0, rain=None),
            _feature("SPLIT", "Split Far", 45.47, -73.74, total=3.0, rain=3.0, snow=0),
        ])
        result = parse_precip_stations(data, LAT, LON)
        assert result["nearest"]["station_id"] == "COMBO"
        assert result["nearest_split"]["station_id"] == "SPLIT"

    def test_nearest_split_equals_nearest_when_nearest_is_split(self):
        """If the nearest reporting station is already split, nearest_split is it."""
        data = _resp([
            _feature("SPLIT", "Split Near", 45.75, -74.02, total=3.0, rain=3.0, snow=0),
            _feature("COMBO", "Combo Far", 45.47, -73.74, total=3.0, rain=None),
        ])
        result = parse_precip_stations(data, LAT, LON)
        assert result["nearest"]["station_id"] == "SPLIT"
        assert result["nearest_split"]["station_id"] == "SPLIT"

    def test_no_split_available(self):
        """Only combined stations exist → nearest_split is None."""
        data = _resp([_feature("C", "Combo", 45.7, -74.0, total=3.0, rain=None)])
        result = parse_precip_stations(data, LAT, LON)
        assert result["nearest"]["station_id"] == "C"
        assert result["nearest_split"] is None


class TestDistance:
    def test_distance_km_is_computed(self):
        """Each candidate carries a distance in km from the reference point."""
        # ~0.09 deg north ≈ 10 km
        data = _resp([_feature("N", "North", LAT + 0.09, LON, total=1.0)])
        result = parse_precip_stations(data, LAT, LON)
        dist = result["nearest"]["distance_km"]
        assert 8 <= dist <= 12, f"expected ~10 km, got {dist}"


class TestFreshness:
    """A station 'reports' precipitation per TestNearestReporting above, but
    EC-wide publication backlogs mean a nearer station's latest value can be
    days stale while a slightly farther station is current. Selection must
    prefer a FRESH station (latest non-null date within 2 days of the window
    end) over a merely-reporting-but-stale one — falling back to the old
    any-non-null-in-window behavior only when nothing nearby is fresh."""

    WINDOW_END = "2026-08-30"

    def test_fresh_nearer_station_wins_over_stale_nearer_still_station(self):
        """A closer station whose latest value is 4 days stale loses to a
        farther station whose latest value is fresh (1 day old)."""
        data = _resp([
            _feature("STALE", "Stale Close", 45.79, -74.01, total=2.0, local_date="2026-08-26"),
            _feature("FRESH", "Fresh Far", 45.47, -73.74, total=1.0, local_date="2026-08-29"),
        ])
        result = parse_precip_stations(data, LAT, LON, window_end=self.WINDOW_END)
        assert result["nearest"]["station_id"] == "FRESH"

    def test_no_fresh_station_anywhere_falls_back_to_legacy_pick(self):
        """When every reporting station is stale (EC-wide backlog), fall back
        to the plain nearest-reporting pick — same as no-freshness-data."""
        data = _resp([
            _feature("NEAR", "Near", 45.79, -74.01, total=2.0, local_date="2026-08-20"),
            _feature("FAR", "Far", 45.10, -73.50, total=1.0, local_date="2026-08-19"),
        ])
        result = parse_precip_stations(data, LAT, LON, window_end=self.WINDOW_END)
        assert result["nearest"]["station_id"] == "NEAR"

    def test_latest_precip_date_is_carried_on_returned_dicts(self):
        """The winning station's latest non-null TOTAL_PRECIPITATION date is
        surfaced as an ISO date string on the returned dict."""
        data = _resp([_feature("S", "S", 45.7, -74.0, total=2.0, local_date="2026-08-29")])
        result = parse_precip_stations(data, LAT, LON, window_end=self.WINDOW_END)
        assert result["nearest"]["latest_precip_date"] == "2026-08-29"

    def test_latest_precip_date_is_none_without_local_date(self):
        """No LOCAL_DATE anywhere in the response → latest_precip_date is
        None (can't establish freshness), same as the legacy-default path."""
        data = _resp([_feature("S", "S", 45.7, -74.0, total=2.0)])
        result = parse_precip_stations(data, LAT, LON, window_end=self.WINDOW_END)
        assert result["nearest"]["latest_precip_date"] is None

    def test_split_selection_honors_freshness_the_same_way(self):
        """nearest_split prefers a fresh split-capable station over a nearer
        but stale split-capable station, mirroring plain 'nearest'."""
        data = _resp([
            _feature("STALE_SPLIT", "Stale Split Close", 45.79, -74.01,
                      total=2.0, rain=2.0, snow=0, local_date="2026-08-26"),
            _feature("FRESH_SPLIT", "Fresh Split Far", 45.47, -73.74,
                      total=1.0, rain=1.0, snow=0, local_date="2026-08-29"),
        ])
        result = parse_precip_stations(data, LAT, LON, window_end=self.WINDOW_END)
        assert result["nearest_split"]["station_id"] == "FRESH_SPLIT"

    def test_split_no_fresh_split_falls_back_to_nearest_split_capable(self):
        """No split-capable station is fresh → fall back to nearest
        split-capable regardless of freshness (mirrors plain 'nearest')."""
        data = _resp([
            _feature("NEAR_SPLIT", "Near Split", 45.79, -74.01,
                      total=2.0, rain=2.0, snow=0, local_date="2026-08-10"),
            _feature("FAR_SPLIT", "Far Split", 45.10, -73.50,
                      total=1.0, rain=1.0, snow=0, local_date="2026-08-09"),
        ])
        result = parse_precip_stations(data, LAT, LON, window_end=self.WINDOW_END)
        assert result["nearest_split"]["station_id"] == "NEAR_SPLIT"

    def test_legacy_default_no_window_end_behaves_exactly_as_before(self):
        """Omitting window_end (the legacy call shape) ignores freshness
        entirely and preserves the old nearest-reporting-wins behavior, even
        when LOCAL_DATE values are present and would otherwise flip the pick."""
        data = _resp([
            _feature("NEAR", "Near", 45.79, -74.01, total=2.0, local_date="2000-01-01"),
            _feature("FAR", "Far", 45.10, -73.50, total=1.0, local_date="2026-08-29"),
        ])
        result = parse_precip_stations(data, LAT, LON)
        assert result["nearest"]["station_id"] == "NEAR"


class TestDiscoverPrecipStationsRequest:
    """discover_precip_stations builds the outbound climate-daily query."""

    LAT, LON = 45.5017, -73.5673

    class _DiscoveryResponse:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        async def json(self):
            return {"features": []}

    async def test_request_url_includes_local_date_property(self):
        """LOCAL_DATE must be requested — Part 1's freshness logic needs it
        to compute each station's latest non-null-precip date."""
        captured_urls: list[str] = []

        class _MockSession:
            def get(self, url, **kw):
                captured_urls.append(url)
                return TestDiscoverPrecipStationsRequest._DiscoveryResponse()

        await discover_precip_stations(
            _MockSession(), self.LAT, self.LON, api_base="https://api.weather.gc.ca",
            timeout=15,
        )

        assert len(captured_urls) == 1
        assert "LOCAL_DATE" in captured_urls[0]

    async def test_window_end_is_passed_through_to_parse(self):
        """discover_precip_stations must thread the window's end date into
        parse_precip_stations so freshness can be evaluated."""
        with patch(
            "ec_weather.api_client.parse_precip_stations",
            return_value={"nearest": None, "nearest_split": None},
        ) as mock_parse:
            class _MockSession:
                def get(self, url, **kw):
                    return TestDiscoverPrecipStationsRequest._DiscoveryResponse()

            await discover_precip_stations(
                _MockSession(), self.LAT, self.LON,
                api_base="https://api.weather.gc.ca", timeout=15,
                window_dates=("2026-08-22", "2026-08-30"),
            )

        mock_parse.assert_called_once()
        assert mock_parse.call_args.kwargs.get("window_end") == "2026-08-30"
