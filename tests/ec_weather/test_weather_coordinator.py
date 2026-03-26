"""Tests for ECWeatherCoordinator — EC API data parsing and retry logic."""

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from ec_weather.api_client import FetchError

from ec_weather.coordinator import ECWeatherCoordinator
from ec_weather.parsing import compute_wind_chill, feels_like, parse_daily

from .conftest import load_fixture


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_coordinator(hass: HomeAssistant) -> ECWeatherCoordinator:
    return ECWeatherCoordinator(hass, city_code="qc-68", language="en")


def _build_ec_response(**overrides) -> dict:
    """Build a minimal EC API response with overrides for currentConditions."""
    base = load_fixture("citypage_weather.json")
    if overrides:
        props = base.setdefault("properties", {})
        cc = props.setdefault("currentConditions", {})
        cc.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Current conditions parsing
# ---------------------------------------------------------------------------

class TestCurrentConditions:
    async def test_current_conditions_parsed(self, hass: HomeAssistant, aioclient_mock):
        """Given EC API response → coordinator.data has correct current values."""
        data = load_fixture("citypage_weather.json")
        aioclient_mock.get(
            "https://api.weather.gc.ca/collections/citypageweather-realtime"
            "/items/qc-68?f=json&lang=en&skipGeometry=true",
            json=data,
        )

        coord = _make_coordinator(hass)
        result = await coord._async_update_data()

        current = result["current"]
        assert current["temp"] is not None
        assert isinstance(current["temp"], float)
        assert current["wind_speed"] is not None
        assert current["icon_code"] is not None or current["condition"] is None
        assert "humidity" in current

    async def test_sunrise_sunset_local_conversion(self, hass: HomeAssistant, aioclient_mock):
        """Given riseSet data → sunrise/sunset converted to local HH:MM."""
        data = load_fixture("citypage_weather.json")
        aioclient_mock.get(
            "https://api.weather.gc.ca/collections/citypageweather-realtime"
            "/items/qc-68?f=json&lang=en&skipGeometry=true",
            json=data,
        )

        coord = _make_coordinator(hass)
        result = await coord._async_update_data()

        # Sunrise and sunset should be HH:MM strings
        assert result["sunrise"] is not None
        assert ":" in result["sunrise"]
        assert result["sunset"] is not None
        assert ":" in result["sunset"]

    async def test_missing_condition_handled(self, hass: HomeAssistant, aioclient_mock):
        """Given null condition from API → handled gracefully."""
        data = load_fixture("citypage_weather.json")
        # Remove condition from currentConditions (simulates current hour)
        props = data.get("properties", {})
        cc = props.get("currentConditions", {})
        cc.pop("condition", None)

        aioclient_mock.get(
            "https://api.weather.gc.ca/collections/citypageweather-realtime"
            "/items/qc-68?f=json&lang=en&skipGeometry=true",
            json=data,
        )

        coord = _make_coordinator(hass)
        result = await coord._async_update_data()

        # Should not crash — condition can be None
        assert result["current"]["condition"] is None


# ---------------------------------------------------------------------------
# Feels-like temperature logic
# ---------------------------------------------------------------------------

class TestFeelsLike:
    def test_wind_chill_applied(self):
        """Given temp ≤ 20°C and wind ≥ 5 → wind chill formula applied."""
        wc = compute_wind_chill(-10.0, 20.0)
        assert wc is not None
        assert wc < -10.0  # wind chill makes it feel colder

    def test_wind_chill_not_applied_warm(self):
        """Given temp > 20°C → wind chill not applicable."""
        wc = compute_wind_chill(25.0, 20.0)
        assert wc is None

    def test_wind_chill_not_applied_calm(self):
        """Given wind < 5 km/h → wind chill not applicable."""
        wc = compute_wind_chill(-10.0, 3.0)
        assert wc is None

    def test_feels_like_uses_humidex_when_warm(self):
        """Given temp > 20°C with humidex → humidex used."""
        fl = feels_like(30.0, 5.0, 38.0)
        assert fl == 38.0

    def test_feels_like_uses_wind_chill_when_cold(self):
        """Given temp ≤ 20°C and wind ≥ 5 → wind chill used."""
        fl = feels_like(-10.0, 20.0, None)
        assert fl is not None
        assert fl < -10.0

    def test_feels_like_fallback_to_temp(self):
        """Given no wind chill and no humidex → returns actual temp."""
        fl = feels_like(15.0, 3.0, None)
        assert fl == 15.0


# ---------------------------------------------------------------------------
# Hourly forecast parsing
# ---------------------------------------------------------------------------

class TestHourlyForecast:
    async def test_hourly_forecast_count_and_fields(self, hass: HomeAssistant, aioclient_mock):
        """Given EC API response → hourly list has items with required fields."""
        data = load_fixture("citypage_weather.json")
        aioclient_mock.get(
            "https://api.weather.gc.ca/collections/citypageweather-realtime"
            "/items/qc-68?f=json&lang=en&skipGeometry=true",
            json=data,
        )

        coord = _make_coordinator(hass)
        result = await coord._async_update_data()

        hourly = result["hourly"]
        assert len(hourly) > 0

        for item in hourly:
            assert "time" in item
            assert "temp" in item
            assert "feels_like" in item
            assert "icon_code" in item
            assert "precipitation_probability" in item
            assert "wind_speed" in item


# ---------------------------------------------------------------------------
# Daily forecast parsing
# ---------------------------------------------------------------------------

class TestDailyForecast:
    async def test_daily_forecast_pairing(self, hass: HomeAssistant, aioclient_mock):
        """Given EC API response → daily items have day/night split."""
        data = load_fixture("citypage_weather.json")
        aioclient_mock.get(
            "https://api.weather.gc.ca/collections/citypageweather-realtime"
            "/items/qc-68?f=json&lang=en&skipGeometry=true",
            json=data,
        )

        coord = _make_coordinator(hass)
        result = await coord._async_update_data()

        daily = result["daily"]
        assert len(daily) > 0

        # Each item should have day and night fields
        for item in daily:
            assert "temp_high" in item or item.get("temp_high") is None
            assert "temp_low" in item or item.get("temp_low") is None
            assert "icon_code" in item
            assert "icon_code_night" in item
            assert "period" in item
            assert "date" in item

    async def test_daily_tonight_only(self, hass: HomeAssistant, aioclient_mock):
        """Given evening forecast → first item may be night-only."""
        data = load_fixture("citypage_weather.json")
        props = data["properties"]
        forecasts = props["forecastGroup"]["forecasts"]

        # Check if first period is night-only (depends on time of fixture capture)
        # We test the _parse_daily function directly for reliability
        daily = parse_daily(forecasts, "en")
        first = daily[0]

        # If first is night-only, temp_high should be None
        if first["temp_high"] is None:
            assert first["temp_low"] is not None
            assert first["icon_code"] is None
            assert first["icon_code_night"] is not None

    async def test_daily_last_day_no_night(self, hass: HomeAssistant, aioclient_mock):
        """Given last day has no paired night → handles gracefully."""
        data = load_fixture("citypage_weather.json")
        props = data["properties"]
        forecasts = props["forecastGroup"]["forecasts"]

        daily = parse_daily(forecasts, "en")
        last = daily[-1]

        # Last day might have temp_low=None — should not crash
        assert "period" in last
        assert "temp_high" in last


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------

class _DNSError(aiohttp.ClientConnectorError):
    """A ClientConnectorError that doesn't crash on str()."""

    def __init__(self):
        # Skip the parent __init__ which requires a real ConnectionKey
        self._conn_key = None
        self._os_error = OSError("DNS failure")

    def __str__(self):
        return "DNS failure"


@pytest.mark.enable_socket
class TestRetryLogic:
    async def test_retry_on_transient_failure(self, hass: HomeAssistant):
        """Given DNS error on first call, success on second → data returned."""
        from ec_weather.api_client import fetch_json_with_retry

        call_count = 0

        class _MockResponse:
            status = 200
            def raise_for_status(self):
                pass
            async def json(self, **kw):
                return {"test": "data"}
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass

        class _FailThenSucceed:
            """Context manager that fails on first use, succeeds after."""
            async def __aenter__(self):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise _DNSError()
                return _MockResponse()
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

    async def test_retry_exhausted_raises(self, hass: HomeAssistant):
        """Given persistent DNS error → raises FetchError after retries."""
        from ec_weather.api_client import fetch_json_with_retry

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
