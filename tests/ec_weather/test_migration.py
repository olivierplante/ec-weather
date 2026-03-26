"""Tests for EC Weather config entry migration (v1 -> v2).

Phase 4.1: mutable settings move from entry.data to entry.options.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from ec_weather.const import (
    CONF_AQHI_INTERVAL,
    CONF_AQHI_LOCATION_ID,
    CONF_BBOX,
    CONF_CITY_CODE,
    CONF_CITY_NAME,
    CONF_GEOMET_BBOX,
    CONF_LANGUAGE,
    CONF_LAT,
    CONF_LON,
    CONF_POLLING_MODE,
    CONF_WEATHER_INTERVAL,
    CONF_WEONG_INTERVAL,
    DEFAULT_AQHI_INTERVAL,
    DEFAULT_POLLING_MODE,
    DEFAULT_WEATHER_INTERVAL,
    DEFAULT_WEONG_INTERVAL,
    DOMAIN,
    POLLING_MODE_EFFICIENT,
    POLLING_MODE_FULL,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

IMMUTABLE_DATA = {
    CONF_CITY_CODE: "on-118",
    CONF_CITY_NAME: "Ottawa",
    CONF_LANGUAGE: "en",
    CONF_LAT: 45.42,
    CONF_LON: -75.70,
    CONF_BBOX: "44.420,-76.700,46.420,-74.700",
    CONF_GEOMET_BBOX: "44.420,-76.700,46.420,-74.700",
    CONF_AQHI_LOCATION_ID: None,
}

MUTABLE_KEYS = {CONF_POLLING_MODE, CONF_WEATHER_INTERVAL, CONF_AQHI_INTERVAL, CONF_WEONG_INTERVAL}


def _make_v1_entry(
    hass: HomeAssistant,
    *,
    extra_data: dict | None = None,
    options: dict | None = None,
) -> tuple[MagicMock, dict]:
    """Build a mock ConfigEntry at VERSION 1."""
    data = {**IMMUTABLE_DATA}
    if extra_data:
        data.update(extra_data)
    entry = MagicMock()
    entry.version = 1
    entry.data = data
    entry.options = options or {}
    entry.entry_id = "test_entry_id"

    # Track calls to async_update_entry
    updated = {}

    def fake_update(entry, **kwargs):
        for k, v in kwargs.items():
            setattr(entry, k, v)
            updated[k] = v

    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = fake_update

    return entry, updated


def _mock_coordinator():
    """Return a mock coordinator with async methods."""
    mock = MagicMock()
    mock.async_config_entry_first_refresh = AsyncMock()
    mock.async_refresh = AsyncMock()
    return mock


# ---------------------------------------------------------------------------
# async_migrate_entry tests
# ---------------------------------------------------------------------------

class TestMigrateEntry:
    """Tests for async_migrate_entry (v1 -> v2)."""

    async def test_migrates_mutable_keys_from_data_to_options(
        self, hass: HomeAssistant,
    ) -> None:
        """V1 entry with mutable settings in data -> settings move to options, version=2."""
        from ec_weather import async_migrate_entry

        mutable_values = {
            CONF_POLLING_MODE: POLLING_MODE_FULL,
            CONF_WEATHER_INTERVAL: 60,
            CONF_AQHI_INTERVAL: 120,
            CONF_WEONG_INTERVAL: 180,
        }
        entry, updated = _make_v1_entry(hass, extra_data=mutable_values)

        result = await async_migrate_entry(hass, entry)

        assert result is True
        assert entry.version == 2

        # Mutable keys must be in options
        for key in MUTABLE_KEYS:
            assert key in entry.options, f"{key} missing from options"
            assert entry.options[key] == mutable_values[key]

        # Mutable keys must NOT be in data
        for key in MUTABLE_KEYS:
            assert key not in entry.data, f"{key} should not be in data"

        # Immutable keys must still be in data
        for key in IMMUTABLE_DATA:
            assert key in entry.data, f"{key} missing from data"

    async def test_migrates_fresh_install_without_mutable_keys(
        self, hass: HomeAssistant,
    ) -> None:
        """V1 entry without mutable keys (fresh install) -> version=2, options empty."""
        from ec_weather import async_migrate_entry

        entry, updated = _make_v1_entry(hass)

        result = await async_migrate_entry(hass, entry)

        assert result is True
        assert entry.version == 2

        # No mutable keys in data — options should be empty
        for key in MUTABLE_KEYS:
            assert key not in entry.options
            assert key not in entry.data

        # Immutable keys untouched
        for key in IMMUTABLE_DATA:
            assert key in entry.data

    async def test_preserves_existing_options(
        self, hass: HomeAssistant,
    ) -> None:
        """V1 entry with pre-existing options -> existing options preserved."""
        from ec_weather import async_migrate_entry

        existing_options = {"some_future_key": "value"}
        mutable_values = {CONF_POLLING_MODE: POLLING_MODE_FULL}
        entry, updated = _make_v1_entry(
            hass, extra_data=mutable_values, options=existing_options,
        )

        result = await async_migrate_entry(hass, entry)

        assert result is True
        assert entry.options["some_future_key"] == "value"
        assert entry.options[CONF_POLLING_MODE] == POLLING_MODE_FULL

    async def test_v2_entry_not_modified(
        self, hass: HomeAssistant,
    ) -> None:
        """V2 entry is returned True without modification."""
        from ec_weather import async_migrate_entry

        entry = MagicMock()
        entry.version = 2
        entry.data = {**IMMUTABLE_DATA}
        entry.options = {CONF_POLLING_MODE: POLLING_MODE_FULL}

        hass.config_entries = MagicMock()

        result = await async_migrate_entry(hass, entry)

        assert result is True
        # async_update_entry should NOT have been called
        hass.config_entries.async_update_entry.assert_not_called()


# ---------------------------------------------------------------------------
# async_setup_entry reads from options
# ---------------------------------------------------------------------------

class TestSetupEntryReadsOptions:
    """async_setup_entry must read mutable settings from entry.options.

    Coordinator constructors are patched to avoid real HA timer scheduling
    and background threads during teardown.
    """

    async def test_reads_intervals_from_options(
        self, hass: HomeAssistant,
    ) -> None:
        """Coordinator intervals come from entry.options, not entry.data."""
        from ec_weather import async_setup_entry
        from .conftest import MOCK_CONFIG_DATA

        entry = MagicMock()
        entry.entry_id = "test_123"
        entry.data = {**MOCK_CONFIG_DATA}
        entry.options = {
            CONF_POLLING_MODE: POLLING_MODE_EFFICIENT,
            CONF_WEATHER_INTERVAL: 45,
            CONF_AQHI_INTERVAL: 90,
            CONF_WEONG_INTERVAL: 240,
        }
        entry.async_create_background_task = lambda h, c, n: c.close()

        hass.data.setdefault(DOMAIN, {})
        hass.services = MagicMock()
        hass.services.has_service = MagicMock(return_value=False)
        hass.config_entries.async_forward_entry_setups = AsyncMock()

        with patch("ec_weather.ECWeatherCoordinator", return_value=_mock_coordinator()) as mock_wc, \
             patch("ec_weather.ECAlertCoordinator", return_value=_mock_coordinator()), \
             patch("ec_weather.ECAQHICoordinator", return_value=_mock_coordinator()) as mock_aqhi, \
             patch("ec_weather.ECWEonGCoordinator", return_value=_mock_coordinator()) as mock_weong:

            result = await async_setup_entry(hass, entry)

        assert result is True

        # Verify ECWeatherCoordinator was called with interval from options
        mock_wc.assert_called_once()
        assert mock_wc.call_args.kwargs.get("interval_minutes") == 45

        # Verify ECWEonGCoordinator was called with interval from options
        mock_weong.assert_called_once()
        assert mock_weong.call_args.kwargs.get("interval_minutes") == 240

        # Verify ECAQHICoordinator was called with interval from options
        mock_aqhi.assert_called_once()
        assert mock_aqhi.call_args.kwargs.get("interval_minutes") == 90

    async def test_falls_back_to_defaults_when_options_empty(
        self, hass: HomeAssistant,
    ) -> None:
        """When options are empty, default intervals are used."""
        from ec_weather import async_setup_entry
        from .conftest import MOCK_CONFIG_DATA

        entry = MagicMock()
        entry.entry_id = "test_456"
        entry.data = {**MOCK_CONFIG_DATA}
        entry.options = {}  # empty — defaults used
        entry.async_create_background_task = lambda h, c, n: c.close()

        hass.data.setdefault(DOMAIN, {})
        hass.services = MagicMock()
        hass.services.has_service = MagicMock(return_value=False)
        hass.config_entries.async_forward_entry_setups = AsyncMock()

        with patch("ec_weather.ECWeatherCoordinator", return_value=_mock_coordinator()) as mock_wc, \
             patch("ec_weather.ECAlertCoordinator", return_value=_mock_coordinator()), \
             patch("ec_weather.ECAQHICoordinator", return_value=_mock_coordinator()) as mock_aqhi, \
             patch("ec_weather.ECWEonGCoordinator", return_value=_mock_coordinator()) as mock_weong:

            result = await async_setup_entry(hass, entry)

        assert result is True

        # Verify defaults used
        mock_wc.assert_called_once()
        assert mock_wc.call_args.kwargs.get("interval_minutes") == DEFAULT_WEATHER_INTERVAL

        mock_weong.assert_called_once()
        assert mock_weong.call_args.kwargs.get("interval_minutes") == DEFAULT_WEONG_INTERVAL

        mock_aqhi.assert_called_once()
        assert mock_aqhi.call_args.kwargs.get("interval_minutes") == DEFAULT_AQHI_INTERVAL

    async def test_does_not_read_mutable_keys_from_data(
        self, hass: HomeAssistant,
    ) -> None:
        """Even if mutable keys are in data (pre-migration), options takes precedence."""
        from ec_weather import async_setup_entry
        from .conftest import MOCK_CONFIG_DATA

        entry = MagicMock()
        entry.entry_id = "test_789"
        # Simulate pre-migration state: mutable keys in data
        entry.data = {
            **MOCK_CONFIG_DATA,
            CONF_WEATHER_INTERVAL: 999,  # should be ignored
        }
        entry.options = {
            CONF_WEATHER_INTERVAL: 45,  # should be used
        }
        entry.async_create_background_task = lambda h, c, n: c.close()

        hass.data.setdefault(DOMAIN, {})
        hass.services = MagicMock()
        hass.services.has_service = MagicMock(return_value=False)
        hass.config_entries.async_forward_entry_setups = AsyncMock()

        with patch("ec_weather.ECWeatherCoordinator", return_value=_mock_coordinator()) as mock_wc, \
             patch("ec_weather.ECAlertCoordinator", return_value=_mock_coordinator()), \
             patch("ec_weather.ECAQHICoordinator", return_value=_mock_coordinator()), \
             patch("ec_weather.ECWEonGCoordinator", return_value=_mock_coordinator()):

            result = await async_setup_entry(hass, entry)

        assert result is True
        # Options value (45) used, not data value (999)
        assert mock_wc.call_args.kwargs.get("interval_minutes") == 45


# ---------------------------------------------------------------------------
# Options flow saves to options, not data
# ---------------------------------------------------------------------------

class TestOptionsFlowSavesToOptions:
    """Options flow must save mutable keys to entry.options, immutable to entry.data."""

    def test_mutable_keys_set(self) -> None:
        """Verify the set of mutable keys matches our expectations."""
        assert MUTABLE_KEYS == {
            CONF_POLLING_MODE, CONF_WEATHER_INTERVAL,
            CONF_AQHI_INTERVAL, CONF_WEONG_INTERVAL,
        }

    def test_options_flow_form_reads_defaults_from_options(self) -> None:
        """The options form defaults for mutable keys should come from entry.options."""
        import inspect
        from ec_weather.config_flow import ECWeatherOptionsFlow

        source = inspect.getsource(ECWeatherOptionsFlow.async_step_init)

        # Verify options flow reads from self.config_entry.options for mutable keys
        assert "self.config_entry.options" in source

        # Verify options flow reads from self.config_entry.data for immutable keys
        assert "self.config_entry.data" in source

    def test_options_flow_splits_user_input(self) -> None:
        """The options flow separates mutable keys into options, immutable into data."""
        import inspect
        from ec_weather.config_flow import ECWeatherOptionsFlow

        source = inspect.getsource(ECWeatherOptionsFlow.async_step_init)

        # Must update both data and options
        assert "new_data" in source
        assert "new_options" in source
        assert "mutable_keys" in source


# ---------------------------------------------------------------------------
# Config flow VERSION
# ---------------------------------------------------------------------------

class TestConfigFlowVersion:
    """ECWeatherConfigFlow.VERSION must be 2 after migration."""

    def test_version_is_2(self) -> None:
        from ec_weather.config_flow import ECWeatherConfigFlow
        assert ECWeatherConfigFlow.VERSION == 2
