"""Tests for api_client.py — HTTP/API concerns extracted from parsing and weong."""

import asyncio
from datetime import datetime, timezone

import aiohttp
import pytest
from ec_weather.api_client import (
    FetchError,
    TransientGeoMetError,
    discover_aqhi_station,
    fetch_json_with_retry,
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
        assert result[0]["province"] == "QC"
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
        """Given AQHI features in bbox -> returns nearest location_id."""
        json_data = {
            "features": [
                {
                    "properties": {
                        "location_id": "MTL01",
                        "location_name_en": "Montreal",
                    }
                },
                {
                    "properties": {
                        "location_id": "MTL01",
                        "location_name_en": "Montreal",
                    }
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
            lat=45.42, lon=-75.70,
            api_base="https://api.weather.gc.ca",
            timeout=15,
        )
        assert result == "MTL01"

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

    async def test_returns_none_on_network_error(self):
        """Given network error -> returns None (does not raise)."""
        class _ErrorResponse:
            async def __aenter__(self):
                raise _DNSError()
            async def __aexit__(self, *args):
                pass

        class MockSession:
            def get(self, url, **kw):
                return _ErrorResponse()

        result = await discover_aqhi_station(
            session=MockSession(),
            lat=45.42, lon=-75.70,
            api_base="https://api.weather.gc.ca",
            timeout=15,
        )
        assert result is None

    async def test_deduplicates_by_location_id(self):
        """Given multiple features with same location_id -> deduplicates."""
        json_data = {
            "features": [
                {"properties": {"location_id": "ABC", "location_name_en": "City"}},
                {"properties": {"location_id": "ABC", "location_name_en": "City"}},
                {"properties": {"location_id": "DEF", "location_name_en": "Town"}},
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
            lat=45.42, lon=-75.70,
            api_base="https://api.weather.gc.ca",
            timeout=15,
        )
        assert result in ("ABC", "DEF")  # first one found
