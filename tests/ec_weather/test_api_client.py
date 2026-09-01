"""Tests for api_client.py — HTTP/API concerns extracted from parsing and weong."""

import asyncio
from datetime import datetime, timezone

import aiohttp
import pytest
from ec_weather.api_client import (
    AqhiDiscoveryError,
    FetchError,
    TransientGeoMetError,
    discover_aqhi_station,
    fetch_json_with_retry,
    find_nearest_complete_city,
    missing_data_points,
    parse_ec_city_features,
    query_geomet_feature_info,
)


# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------

class _DNSError(aiohttp.ClientConnectorError):
    """A ClientConnectorError that doesn't crash on str()."""

    def __init__(self):
        self._conn_key = None
        self._os_error = OSError("DNS failure")

    def __str__(self):
        return "DNS failure"


class _MockResponse:
    """A mock aiohttp response that returns JSON."""

    def __init__(self, json_data, status=200, content_type="application/json"):
        self._json_data = json_data
        self.status = status
        self._content_type = content_type

    def raise_for_status(self):
        if self.status >= 400:
            raise aiohttp.ClientResponseError(
                request_info=None, history=(),
                status=self.status, message="Error",
            )

    async def json(self, **kw):
        return self._json_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class _SimpleSession:
    """Mock session that returns a fixed response."""

    def __init__(self, response):
        self._response = response

    def get(self, url, **kw):
        return self._response


# ---------------------------------------------------------------------------
# fetch_json_with_retry tests (moved from test_weather_coordinator.py)
# ---------------------------------------------------------------------------

@pytest.mark.enable_socket
class TestFetchJsonWithRetry:
    async def test_retry_on_transient_failure(self):
        """Given DNS error on first call, success on second -> data returned."""
        call_count = 0

        class _FailThenSucceed:
            async def __aenter__(self):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise _DNSError()
                return _MockResponse({"test": "data"})
            async def __aexit__(self, *args):
                pass

        class MockSession:
            def get(self, url, **kw):
                return _FailThenSucceed()

        result = await fetch_json_with_retry(
            MockSession(), "http://test", retries=3, retry_delay=0, label="test",
        )
        assert result == {"test": "data"}
        assert call_count == 2  # failed once, succeeded on retry

    async def test_retry_exhausted_raises(self):
        """Given persistent DNS error -> raises FetchError after retries."""
        class _AlwaysFail:
            async def __aenter__(self):
                raise _DNSError()
            async def __aexit__(self, *args):
                pass

        class MockSession:
            def get(self, url, **kw):
                return _AlwaysFail()

        with pytest.raises(FetchError, match="DNS failure"):
            await fetch_json_with_retry(
                MockSession(), "http://test", retries=3, retry_delay=0, label="test",
            )

    async def test_retry_on_timeout(self):
        """Given timeout on first call, success on second -> data returned."""
        call_count = 0

        class _TimeoutThenSucceed:
            async def __aenter__(self):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise asyncio.TimeoutError()
                return _MockResponse({"ok": True})
            async def __aexit__(self, *args):
                pass

        class MockSession:
            def get(self, url, **kw):
                return _TimeoutThenSucceed()

        result = await fetch_json_with_retry(
            MockSession(), "http://test", retries=2, retry_delay=0, label="test",
        )
        assert result == {"ok": True}
        assert call_count == 2

    async def test_http_error_not_retried(self):
        """Given HTTP 500 -> raises FetchError immediately (no retry)."""
        call_count = 0

        class _Http500:
            async def __aenter__(self):
                nonlocal call_count
                call_count += 1
                return self
            async def __aexit__(self, *args):
                pass
            def raise_for_status(self):
                raise aiohttp.ClientResponseError(
                    request_info=aiohttp.RequestInfo(
                        url="http://test",
                        method="GET",
                        headers={},
                        real_url="http://test",
                    ),
                    history=(),
                    status=500,
                    message="Internal Server Error",
                )
            async def json(self, **kw):
                return {}

        class MockSession:
            def get(self, url, **kw):
                return _Http500()

        with pytest.raises(FetchError, match="Error fetching"):
            await fetch_json_with_retry(
                MockSession(), "http://test", retries=3, retry_delay=0, label="test",
            )
        assert call_count == 1  # no retries

    async def test_json_parse_error_not_retried(self):
        """Given JSON parse error -> raises FetchError immediately."""
        call_count = 0

        class _BadJson:
            async def __aenter__(self):
                nonlocal call_count
                call_count += 1
                return self
            async def __aexit__(self, *args):
                pass
            def raise_for_status(self):
                pass
            async def json(self, **kw):
                raise ValueError("Expecting value")

        class MockSession:
            def get(self, url, **kw):
                return _BadJson()

        with pytest.raises(FetchError, match="Error parsing"):
            await fetch_json_with_retry(
                MockSession(), "http://test", retries=3, retry_delay=0, label="test",
            )
        assert call_count == 1

    async def test_success_on_first_try(self):
        """Given a healthy endpoint -> returns JSON immediately."""
        class _OkResponse:
            async def __aenter__(self):
                return _MockResponse({"status": "ok"})
            async def __aexit__(self, *args):
                pass

        class MockSession:
            def get(self, url, **kw):
                return _OkResponse()

        result = await fetch_json_with_retry(
            MockSession(), "http://test", retries=3, retry_delay=0, label="test",
        )
        assert result == {"status": "ok"}


# ---------------------------------------------------------------------------
# query_geomet_feature_info tests
# ---------------------------------------------------------------------------

@pytest.mark.enable_socket
class TestQueryGeometFeatureInfo:
    async def test_returns_float_value(self):
        """Given GeoMet response with features -> returns float value."""
        json_data = {
            "features": [
                {"properties": {"value": 42.5}}
            ]
        }

        class _GeoMetResponse:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            def raise_for_status(self):
                pass
            async def json(self, **kw):
                return json_data

        class MockSession:
            def get(self, url, **kw):
                return _GeoMetResponse()

        value, ref_dt = await query_geomet_feature_info(
            session=MockSession(),
            geomet_bbox="44.420,-76.700,46.420,-74.700",
            layer="HRDPS-WEonG_2.5km_Precip-Prob",
            timestep=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
            timeout=10,
        )
        assert value == 42.5

    async def test_returns_none_for_empty_features(self):
        """Given GeoMet response with empty features -> returns None."""
        json_data = {"features": []}

        class _EmptyResponse:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            def raise_for_status(self):
                pass
            async def json(self, **kw):
                return json_data

        class MockSession:
            def get(self, url, **kw):
                return _EmptyResponse()

        value, ref_dt = await query_geomet_feature_info(
            session=MockSession(),
            geomet_bbox="44.420,-76.700,46.420,-74.700",
            layer="HRDPS-WEonG_2.5km_Precip-Prob",
            timestep=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
            timeout=10,
        )
        assert value is None
        assert ref_dt is None

    async def test_raises_transient_error_on_timeout(self):
        """Given timeout -> raises TransientGeoMetError."""
        class _TimeoutResponse:
            async def __aenter__(self):
                raise asyncio.TimeoutError()
            async def __aexit__(self, *args):
                pass

        class MockSession:
            def get(self, url, **kw):
                return _TimeoutResponse()

        with pytest.raises(TransientGeoMetError):
            await query_geomet_feature_info(
                session=MockSession(),
                geomet_bbox="44.420,-76.700,46.420,-74.700",
                layer="HRDPS-WEonG_2.5km_Precip-Prob",
                timestep=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
                timeout=10,
            )

    async def test_raises_transient_error_on_client_error(self):
        """Given connection error -> raises TransientGeoMetError."""
        class _ConnErrorResponse:
            async def __aenter__(self):
                raise _DNSError()
            async def __aexit__(self, *args):
                pass

        class MockSession:
            def get(self, url, **kw):
                return _ConnErrorResponse()

        with pytest.raises(TransientGeoMetError):
            await query_geomet_feature_info(
                session=MockSession(),
                geomet_bbox="44.420,-76.700,46.420,-74.700",
                layer="HRDPS-WEonG_2.5km_Precip-Prob",
                timestep=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
                timeout=10,
            )

    async def test_returns_none_for_null_value(self):
        """Given GeoMet feature with value=null -> returns None."""
        json_data = {
            "features": [
                {"properties": {"value": None}}
            ]
        }

        class _NullValueResponse:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            def raise_for_status(self):
                pass
            async def json(self, **kw):
                return json_data

        class MockSession:
            def get(self, url, **kw):
                return _NullValueResponse()

        value, ref_dt = await query_geomet_feature_info(
            session=MockSession(),
            geomet_bbox="44.420,-76.700,46.420,-74.700",
            layer="HRDPS-WEonG_2.5km_Precip-Prob",
            timestep=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
            timeout=10,
        )
        assert value is None

    async def test_builds_correct_url(self):
        """Given parameters -> builds correct GeoMet WMS URL."""
        captured_url = None

        class _UrlCapture:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            def raise_for_status(self):
                pass
            async def json(self, **kw):
                return {"features": []}

        class MockSession:
            def get(self, url, **kw):
                nonlocal captured_url
                captured_url = url
                return _UrlCapture()

        await query_geomet_feature_info(
            session=MockSession(),
            geomet_bbox="44.420,-76.700,46.420,-74.700",
            layer="HRDPS-WEonG_2.5km_Precip-Prob",
            timestep=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
            timeout=10,
        )
        assert captured_url is not None
        assert "LAYERS=HRDPS-WEonG_2.5km_Precip-Prob" in captured_url
        assert "BBOX=44.420,-76.700,46.420,-74.700" in captured_url
        assert "TIME=2026-03-22T12:00:00Z" in captured_url
        assert "CRS=EPSG:4326" in captured_url

    async def test_raises_rate_limited_on_429(self):
        """A HTTP 429 must surface as RateLimitedError (a TransientGeoMetError
        subclass) so callers both refuse to cache it and can pace the wave."""
        from ec_weather.api_client import RateLimitedError

        class _RateLimitedResponse:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def raise_for_status(self):
                raise aiohttp.ClientResponseError(
                    request_info=None, history=(),
                    status=429, message="Too Many Requests",
                )

            async def json(self, **kw):
                return {}

        class MockSession:
            def get(self, url, **kw):
                return _RateLimitedResponse()

        with pytest.raises(RateLimitedError):
            await query_geomet_feature_info(
                session=MockSession(),
                geomet_bbox="44.420,-76.700,46.420,-74.700",
                layer="HRDPS-WEonG_2.5km_Precip-Prob",
                timestep=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
                timeout=10,
            )
        # A RateLimitedError is still a TransientGeoMetError (never cached).
        assert issubclass(RateLimitedError, TransientGeoMetError)

    async def test_non_429_http_error_raises_transient(self):
        """A non-429 HTTP error stays a plain TransientGeoMetError (no backoff)."""
        from ec_weather.api_client import RateLimitedError

        class _ServerErrorResponse:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def raise_for_status(self):
                raise aiohttp.ClientResponseError(
                    request_info=None, history=(),
                    status=503, message="Service Unavailable",
                )

            async def json(self, **kw):
                return {}

        class MockSession:
            def get(self, url, **kw):
                return _ServerErrorResponse()

        with pytest.raises(TransientGeoMetError) as exc_info:
            await query_geomet_feature_info(
                session=MockSession(),
                geomet_bbox="44.420,-76.700,46.420,-74.700",
                layer="HRDPS-WEonG_2.5km_Precip-Prob",
                timestep=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
                timeout=10,
            )
        assert not isinstance(exc_info.value, RateLimitedError)


# ---------------------------------------------------------------------------
# parse_ec_city_features tests
# ---------------------------------------------------------------------------

class TestParseEcCityFeatures:
    def test_parses_standard_features(self):
        """Given EC city features -> returns list of city dicts."""
        features = [
            {
                "id": "on-118",
                "properties": {
                    "name": {"en": "Ottawa", "fr": "Ottawa"},
                    "url": {
                        "en": "https://weather.gc.ca/city/pages/on-118_metric_e.html?coords=45.42,-75.70"
                    },
                },
            },
            {
                "id": "on-143",
                "properties": {
                    "name": {"en": "Toronto", "fr": "Toronto"},
                    "url": {
                        "en": "https://weather.gc.ca/city/pages/on-143_metric_e.html?coords=43.67,-79.40"
                    },
                },
            },
        ]

        result = parse_ec_city_features(features, language="en")

        assert len(result) == 2
        assert result[0]["id"] == "on-118"
        assert result[0]["name"] == "Ottawa"
        assert result[0]["province"] == "ON"
        assert result[0]["lat"] == 45.42
        assert result[0]["lon"] == -75.70
        assert result[1]["id"] == "on-143"
        assert result[1]["name"] == "Toronto"

    def test_french_language(self):
        """Given language=fr -> uses French name."""
        features = [
            {
                "id": "on-118",
                "properties": {
                    "name": {"en": "Ottawa", "fr": "Ottawa"},
                    "url": {
                        "en": "https://weather.gc.ca/city/pages/on-118_metric_e.html?coords=45.42,-75.70"
                    },
                },
            },
        ]

        result = parse_ec_city_features(features, language="fr")
        assert result[0]["name"] == "Ottawa"

    def test_missing_name_uses_id(self):
        """Given feature with missing name -> falls back to id."""
        features = [
            {
                "id": "qc-99",
                "properties": {
                    "name": {},
                    "url": {"en": "https://example.com?coords=46.0,-73.0"},
                },
            },
        ]

        result = parse_ec_city_features(features, language="en")
        assert result[0]["name"] == "qc-99"

    def test_no_coords_in_url(self):
        """Given feature with no coords in URL -> lat/lon are None."""
        features = [
            {
                "id": "qc-99",
                "properties": {
                    "name": {"en": "TestCity"},
                    "url": {"en": "https://example.com/no-coords"},
                },
            },
        ]

        result = parse_ec_city_features(features, language="en")
        assert result[0]["lat"] is None
        assert result[0]["lon"] is None

    def test_empty_features(self):
        """Given empty features list -> returns empty list."""
        result = parse_ec_city_features([], language="en")
        assert result == []

    def test_province_from_city_code(self):
        """Given city code with province prefix -> province extracted."""
        features = [
            {
                "id": "bc-74",
                "properties": {
                    "name": {"en": "Vancouver"},
                    "url": {"en": "https://example.com?coords=49.28,-123.12"},
                },
            },
        ]

        result = parse_ec_city_features(features, language="en")
        assert result[0]["province"] == "BC"

    def test_name_is_string_not_dict(self):
        """Given feature where name is a plain string -> uses it directly."""
        features = [
            {
                "id": "on-118",
                "properties": {
                    "name": "Ottawa",
                    "url": {"en": "https://example.com?coords=45.42,-75.70"},
                },
            },
        ]

        result = parse_ec_city_features(features, language="en")
        assert result[0]["name"] == "Ottawa"


# ---------------------------------------------------------------------------
# discover_aqhi_station tests
# ---------------------------------------------------------------------------

@pytest.mark.enable_socket
class TestDiscoverAqhiStation:
    async def test_returns_station_id(self):
        """Given fresh AQHI features in bbox -> returns nearest location_id.

        Geometry and a current-or-future forecast_datetime are required on
        every row now: EC removed location_latitude/location_longitude from
        item properties, and the datetime= query filter no longer matches
        rows on this collection, so freshness is judged client-side.
        """
        json_data = {
            "features": [
                {
                    "properties": {
                        "location_id": "TESTA",
                        "location_name_en": "Test Station A",
                        "forecast_datetime": "2100-01-01T00:00:00Z",
                    },
                    "geometry": {"type": "Point", "coordinates": [-73.5673, 45.5017]},
                },
                {
                    "properties": {
                        "location_id": "TESTA",
                        "location_name_en": "Test Station A",
                        "forecast_datetime": "2100-01-01T01:00:00Z",
                    },
                    "geometry": {"type": "Point", "coordinates": [-73.5673, 45.5017]},
                },
            ]
        }

        class _AqhiResponse:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            def raise_for_status(self):
                pass
            async def json(self, **kw):
                return json_data

        class MockSession:
            def get(self, url, **kw):
                return _AqhiResponse()

        result = await discover_aqhi_station(
            session=MockSession(),
            lat=45.5017, lon=-73.5673,
            api_base="https://api.weather.gc.ca",
            timeout=15,
        )
        assert result == "TESTA"

    async def test_returns_none_for_empty_features(self):
        """Given no AQHI features -> returns None."""
        json_data = {"features": []}

        class _EmptyResponse:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            def raise_for_status(self):
                pass
            async def json(self, **kw):
                return json_data

        class MockSession:
            def get(self, url, **kw):
                return _EmptyResponse()

        result = await discover_aqhi_station(
            session=MockSession(),
            lat=45.42, lon=-75.70,
            api_base="https://api.weather.gc.ca",
            timeout=15,
        )
        assert result is None

    async def test_raises_aqhi_discovery_error_on_network_error(self):
        """Given network error -> raises AqhiDiscoveryError (does not return None).

        A network failure must be distinguishable from EC genuinely answering
        "no station here" — see test_returns_none_for_empty_features. The
        caller (coordinator self-heal) needs this distinction to avoid
        burning its 24h rediscovery rate-limit on a transient error.
        """
        class _ErrorResponse:
            async def __aenter__(self):
                raise _DNSError()
            async def __aexit__(self, *args):
                pass

        class MockSession:
            def get(self, url, **kw):
                return _ErrorResponse()

        with pytest.raises(AqhiDiscoveryError):
            await discover_aqhi_station(
                session=MockSession(),
                lat=45.42, lon=-75.70,
                api_base="https://api.weather.gc.ca",
                timeout=15,
            )

    async def test_deduplicates_by_location_id(self):
        """Given multiple features with same location_id -> deduplicates."""
        json_data = {
            "features": [
                {
                    "properties": {
                        "location_id": "TESTA",
                        "location_name_en": "City",
                        "forecast_datetime": "2100-01-01T00:00:00Z",
                    },
                    "geometry": {"type": "Point", "coordinates": [-73.5673, 45.5017]},
                },
                {
                    "properties": {
                        "location_id": "TESTA",
                        "location_name_en": "City",
                        "forecast_datetime": "2100-01-01T01:00:00Z",
                    },
                    "geometry": {"type": "Point", "coordinates": [-73.5673, 45.5017]},
                },
                {
                    "properties": {
                        "location_id": "TESTB",
                        "location_name_en": "Town",
                        "forecast_datetime": "2100-01-01T00:00:00Z",
                    },
                    "geometry": {"type": "Point", "coordinates": [-73.6, 45.6]},
                },
            ]
        }

        class _MultiResponse:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            def raise_for_status(self):
                pass
            async def json(self, **kw):
                return json_data

        class MockSession:
            def get(self, url, **kw):
                return _MultiResponse()

        # Should return first unique station
        result = await discover_aqhi_station(
            session=MockSession(),
            lat=45.5017, lon=-73.5673,
            api_base="https://api.weather.gc.ca",
            timeout=15,
        )
        assert result in ("TESTA", "TESTB")  # first one found

    async def test_builds_correct_url(self):
        """Discovery URL has no datetime= filter and no skipGeometry — EC
        removed location_latitude/location_longitude from item properties
        and broke datetime= row-matching on this collection (Sept 2026) — and
        requests only the properties that still exist."""
        captured_url = None

        class _UrlCapture:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            def raise_for_status(self):
                pass
            async def json(self, **kw):
                return {"features": []}

        class MockSession:
            def get(self, url, **kw):
                nonlocal captured_url
                captured_url = url
                return _UrlCapture()

        await discover_aqhi_station(
            session=MockSession(),
            lat=45.5017, lon=-73.5673,
            api_base="https://api.weather.gc.ca",
            timeout=15,
        )
        assert captured_url is not None
        assert "datetime=" not in captured_url
        assert "skipGeometry" not in captured_url
        # Newest-first sort keeps every currently-publishing station's fresh
        # rows inside the 200-row page, so pagination can't hide freshness.
        assert "sortby=-forecast_datetime" in captured_url
        assert (
            "properties=location_id,location_name_en,forecast_datetime"
            in captured_url
        )

    async def test_skips_stale_station_favors_fresher_farther_station(self):
        """The nearest station's rows are all past-dated — it must not be
        selected as its own replacement even though it's closest; the
        farther but currently-fresh station is picked instead."""
        json_data = {
            "features": [
                {
                    "properties": {
                        "location_id": "TESTNEAR",
                        "location_name_en": "Retired Near Station",
                        "forecast_datetime": "2000-01-01T00:00:00Z",
                    },
                    "geometry": {"type": "Point", "coordinates": [-73.5673, 45.5017]},
                },
                {
                    "properties": {
                        "location_id": "TESTFAR",
                        "location_name_en": "Healthy Far Station",
                        "forecast_datetime": "2100-01-01T00:00:00Z",
                    },
                    "geometry": {"type": "Point", "coordinates": [-74.5, 46.5]},
                },
            ]
        }

        class _StaleNearResponse:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            def raise_for_status(self):
                pass
            async def json(self, **kw):
                return json_data

        class MockSession:
            def get(self, url, **kw):
                return _StaleNearResponse()

        result = await discover_aqhi_station(
            session=MockSession(),
            lat=45.5017, lon=-73.5673,
            api_base="https://api.weather.gc.ca",
            timeout=15,
        )
        assert result == "TESTFAR"

    async def test_reads_coordinates_from_geometry_and_picks_nearest(self):
        """Station coordinates come only from feature geometry now (the
        location_latitude/location_longitude properties are gone), and must
        be read in GeoJSON [lon, lat] order — not [lat, lon].

        TESTA's geometry is genuinely near the query point in the correct
        [lon, lat] reading. TESTB's geometry is deliberately the query
        point's (lat, lon) written in [lon, lat] slots — it only lands on
        top of the query point if the coordinate order is read backwards.
        A lon/lat swap bug would make TESTB win instead of TESTA.
        """
        json_data = {
            "features": [
                {
                    "properties": {
                        "location_id": "TESTA",
                        "location_name_en": "Genuinely Near Station",
                        "forecast_datetime": "2100-01-01T00:00:00Z",
                    },
                    "geometry": {"type": "Point", "coordinates": [-73.6, 45.55]},
                },
                {
                    "properties": {
                        "location_id": "TESTB",
                        "location_name_en": "Near Only If Swapped",
                        "forecast_datetime": "2100-01-01T00:00:00Z",
                    },
                    "geometry": {"type": "Point", "coordinates": [45.5017, -73.5673]},
                },
            ]
        }

        class _GeometryResponse:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            def raise_for_status(self):
                pass
            async def json(self, **kw):
                return json_data

        class MockSession:
            def get(self, url, **kw):
                return _GeometryResponse()

        result = await discover_aqhi_station(
            session=MockSession(),
            lat=45.5017, lon=-73.5673,
            api_base="https://api.weather.gc.ca",
            timeout=15,
        )
        assert result == "TESTA"


# ---------------------------------------------------------------------------
# missing_data_points tests
# ---------------------------------------------------------------------------

class TestMissingDataPoints:
    """Tests for missing_data_points — pure function, no HA needed."""

    def test_fully_reporting_returns_empty(self):
        """A citypage with every current-conditions field -> no gaps."""
        props = {
            "currentConditions": {
                "condition": {"en": "Sunny"},
                "iconCode": {"value": {"en": "00"}},
                "temperature": {"value": {"en": -1.7}},
                "relativeHumidity": {"value": {"en": 76}},
                "wind": {"speed": {"value": {"en": 6}}},
            }
        }
        assert missing_data_points(props) == []

    def test_auto_station_missing_sky_condition(self):
        """No condition text and no iconCode value -> sky_condition missing."""
        props = {
            "currentConditions": {
                "iconCode": {"format": "gif"},
                "temperature": {"value": {"en": -1.7}},
                "relativeHumidity": {"value": {"en": 76}},
                "wind": {"speed": {"value": {"en": 6}}},
            }
        }
        assert missing_data_points(props) == ["sky_condition"]

    def test_missing_humidity(self):
        """No relativeHumidity block -> humidity is reported missing."""
        props = {
            "currentConditions": {
                "condition": {"en": "Sunny"},
                "temperature": {"value": {"en": -1.7}},
                "wind": {"speed": {"value": {"en": 6}}},
            }
        }
        assert missing_data_points(props) == ["humidity"]

    def test_calm_wind_speed_not_missing(self):
        """A wind speed value of the string 'calm' still counts as present."""
        props = {
            "currentConditions": {
                "condition": {"en": "Sunny"},
                "temperature": {"value": {"en": -1.7}},
                "relativeHumidity": {"value": {"en": 76}},
                "wind": {"speed": {"value": {"en": "calm"}}},
            }
        }
        assert missing_data_points(props) == []

    def test_condition_null_but_icon_code_present_not_missing(self):
        """condition.en is null but iconCode.value.en exists -> not missing."""
        props = {
            "currentConditions": {
                "condition": {"en": None},
                "iconCode": {"value": {"en": "00"}},
                "temperature": {"value": {"en": -1.7}},
                "relativeHumidity": {"value": {"en": 76}},
                "wind": {"speed": {"value": {"en": 6}}},
            }
        }
        assert missing_data_points(props) == []

    def test_empty_props_returns_all_in_stable_order(self):
        """No currentConditions at all -> every data point missing, stable order."""
        assert missing_data_points({}) == [
            "sky_condition", "temperature", "humidity", "wind_speed",
        ]


# ---------------------------------------------------------------------------
# parse_ec_city_features: "missing" field tests
# ---------------------------------------------------------------------------

class TestParseEcCityFeaturesMissing:
    """Tests that parse_ec_city_features attaches missing_data_points output."""

    def test_auto_station_city_carries_missing_list(self):
        """A city backed by an auto station carries its missing data points."""
        features = [
            {
                "id": "bc-66",
                "properties": {
                    "name": {"en": "TestCity"},
                    "url": {"en": "https://example.com?coords=48.4283,-123.3696"},
                    "currentConditions": {
                        "iconCode": {"format": "gif"},
                        "temperature": {"value": {"en": 10}},
                        "relativeHumidity": {"value": {"en": 80}},
                        "wind": {"speed": {"value": {"en": 5}}},
                    },
                },
            },
        ]
        result = parse_ec_city_features(features, language="en")
        assert result[0]["missing"] == ["sky_condition"]

    def test_fully_reporting_city_has_empty_missing(self):
        """A citypage that reports everything carries an empty missing list."""
        features = [
            {
                "id": "on-118",
                "properties": {
                    "name": {"en": "Ottawa"},
                    "url": {"en": "https://example.com?coords=45.4215,-75.6972"},
                    "currentConditions": {
                        "condition": {"en": "Sunny"},
                        "iconCode": {"value": {"en": "00"}},
                        "temperature": {"value": {"en": 10}},
                        "relativeHumidity": {"value": {"en": 80}},
                        "wind": {"speed": {"value": {"en": 5}}},
                    },
                },
            },
        ]
        result = parse_ec_city_features(features, language="en")
        assert result[0]["missing"] == []


# ---------------------------------------------------------------------------
# find_nearest_complete_city tests
# ---------------------------------------------------------------------------

def _citypage_feature(city_id: str, lat: float, lon: float, complete: bool) -> dict:
    """Build a citypage feature shaped like the reduced-properties response."""
    current = {
        "temperature": {"value": {"en": 10}},
        "relativeHumidity": {"value": {"en": 80}},
        "wind": {"speed": {"value": {"en": 5}}},
    }
    if complete:
        current["condition"] = {"en": "Sunny"}
    return {
        "id": city_id,
        "properties": {
            "name": {"en": city_id},
            "url": {"en": f"https://example.com?coords={lat},{lon}"},
            "currentConditions": current,
        },
    }


class _SequenceSession:
    """Mock session returning successive JSON responses, one per call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def get(self, url, **kw):
        self.calls += 1
        return _MockResponse(self._responses.pop(0))


@pytest.mark.enable_socket
class TestFindNearestCompleteCity:
    """Tests for find_nearest_complete_city — ring expansion + haversine pick."""

    async def test_expands_to_second_ring_when_first_has_none_complete(self):
        """First ring: only incomplete candidates -> expands and finds one."""
        ring1 = {"features": [_citypage_feature("qc-01", 45.51, -73.57, False)]}
        ring2 = {
            "features": [
                _citypage_feature("qc-01", 45.51, -73.57, False),
                _citypage_feature("qc-02", 45.60, -73.60, True),
            ]
        }
        session = _SequenceSession([ring1, ring2])

        result = await find_nearest_complete_city(
            session=session, lat=45.5017, lon=-73.5673,
            exclude_id="qc-99", api_base="https://api.weather.gc.ca", timeout=15,
        )

        assert session.calls == 2
        assert result is not None
        assert result["id"] == "qc-02"

    async def test_no_complete_candidate_in_any_ring_returns_none(self):
        """No fully-reporting candidate through all three rings -> None."""
        incomplete = {"features": [_citypage_feature("qc-01", 45.51, -73.57, False)]}
        session = _SequenceSession([incomplete, incomplete, incomplete])

        result = await find_nearest_complete_city(
            session=session, lat=45.5017, lon=-73.5673,
            exclude_id="qc-99", api_base="https://api.weather.gc.ca", timeout=15,
        )

        assert session.calls == 3
        assert result is None

    async def test_closest_of_two_complete_candidates_wins(self):
        """Two complete candidates in the same ring -> nearest by haversine."""
        ring1 = {
            "features": [
                _citypage_feature("qc-far", 46.5, -74.5, True),
                _citypage_feature("qc-near", 45.55, -73.60, True),
            ]
        }
        session = _SequenceSession([ring1])

        result = await find_nearest_complete_city(
            session=session, lat=45.5017, lon=-73.5673,
            exclude_id="qc-99", api_base="https://api.weather.gc.ca", timeout=15,
        )

        assert result["id"] == "qc-near"
        assert isinstance(result["distance_km"], int)

    async def test_candidate_matching_exclude_id_is_skipped(self):
        """A complete candidate equal to exclude_id doesn't count as a match."""
        ring1 = {
            "features": [_citypage_feature("qc-excluded", 45.51, -73.57, True)]
        }
        ring2 = {
            "features": [
                _citypage_feature("qc-excluded", 45.51, -73.57, True),
                _citypage_feature("qc-alt", 45.60, -73.60, True),
            ]
        }
        session = _SequenceSession([ring1, ring2])

        result = await find_nearest_complete_city(
            session=session, lat=45.5017, lon=-73.5673,
            exclude_id="qc-excluded", api_base="https://api.weather.gc.ca",
            timeout=15,
        )

        assert result["id"] == "qc-alt"

    async def test_network_error_returns_none(self):
        """A network error on any ring returns None (does not raise)."""
        class _ErrorResponse:
            async def __aenter__(self):
                raise _DNSError()
            async def __aexit__(self, *args):
                pass

        class MockSession:
            def get(self, url, **kw):
                return _ErrorResponse()

        result = await find_nearest_complete_city(
            session=MockSession(), lat=45.5017, lon=-73.5673,
            exclude_id="qc-99", api_base="https://api.weather.gc.ca", timeout=15,
        )

        assert result is None
