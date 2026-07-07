"""Tests for nearest precipitation-station discovery (issue #9, Part B).

EC ``climate-daily`` is mostly a dead historical archive — most stations in
any bbox report null precipitation. Discovery must pick the nearest station
that *actually* reports precipitation (non-null TOTAL_PRECIPITATION over a
recent window), and separately surface the nearest station that reports the
rain/snow split (non-null TOTAL_RAIN on any day in the window).

``parse_precip_stations`` is the pure aggregator over a windowed API response.
"""

from __future__ import annotations

from ec_weather.api_client import parse_precip_stations


def _feature(station_id, name, lat, lon, total, rain=None, snow=None):
    return {
        "geometry": {"coordinates": [lon, lat]},
        "properties": {
            "CLIMATE_IDENTIFIER": station_id,
            "STATION_NAME": name,
            "TOTAL_PRECIPITATION": total,
            "TOTAL_RAIN": rain,
            "TOTAL_SNOW": snow,
        },
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
