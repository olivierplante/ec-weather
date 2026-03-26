"""Tests for the ECWeather entity — ensures merge parameters are passed correctly.

These tests exist specifically to prevent regressions where new parameters
added to merge/transform functions are not propagated through the weather entity.
"""

from __future__ import annotations

import inspect

from ec_weather.transforms import merge_weong_into_daily, build_unified_hourly
from ec_weather.weather import ECWeather


class TestMergeWeongSignatureSync:
    """Verify that the weather entity passes all required parameters to merge functions.

    When new parameters are added to merge_weong_into_daily or build_unified_hourly,
    the weather entity must pass them. These tests catch missing parameter regressions.
    """

    def test_merge_weong_into_daily_has_lang_param(self) -> None:
        """merge_weong_into_daily must accept a lang parameter."""
        sig = inspect.signature(merge_weong_into_daily)
        assert "lang" in sig.parameters, (
            "merge_weong_into_daily is missing 'lang' parameter — "
            "was it removed or renamed?"
        )

    def test_merge_weong_into_daily_has_hourly_forecast_param(self) -> None:
        """merge_weong_into_daily must accept hourly_forecast for timestep enrichment."""
        sig = inspect.signature(merge_weong_into_daily)
        assert "hourly_forecast" in sig.parameters, (
            "merge_weong_into_daily is missing 'hourly_forecast' parameter"
        )

    def test_build_unified_hourly_has_lang_param(self) -> None:
        """build_unified_hourly must accept a lang parameter."""
        sig = inspect.signature(build_unified_hourly)
        assert "lang" in sig.parameters, (
            "build_unified_hourly is missing 'lang' parameter"
        )

    def test_weather_entity_stores_language(self) -> None:
        """ECWeather must accept and store a language parameter."""
        sig = inspect.signature(ECWeather.__init__)
        assert "language" in sig.parameters, (
            "ECWeather.__init__ is missing 'language' parameter — "
            "it must pass lang to merge_weong_into_daily"
        )


class TestWeatherEntityForecastMerge:
    """Test that async_forecast_daily passes hourly data and lang to the merge function."""

    def test_async_forecast_daily_calls_merge_with_hourly(self) -> None:
        """async_forecast_daily must pass hourly forecast data to merge_weong_into_daily.

        Without this, timestep enrichment doesn't happen and daily popups
        show empty timelines with missing icons and temperatures.
        """
        source = inspect.getsource(ECWeather.async_forecast_daily)
        # The merge call must include hourly data (3rd positional arg or hourly= kwarg)
        assert "hourly" in source and "merge_weong_into_daily" in source, (
            "async_forecast_daily must pass hourly data to merge_weong_into_daily — "
            "without it, daily popup timesteps won't be enriched with EC hourly data"
        )

    def test_async_forecast_daily_calls_merge_with_lang(self) -> None:
        """async_forecast_daily must pass lang to merge_weong_into_daily."""
        source = inspect.getsource(ECWeather.async_forecast_daily)
        assert "lang=" in source or "self._language" in source, (
            "async_forecast_daily must pass language to merge_weong_into_daily"
        )
