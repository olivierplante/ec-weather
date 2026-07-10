"""Tests for the ec_weather/entities websocket discovery command (Phase 1).

The card resolves its entities at runtime by a stable machine-readable role
rather than a hardcoded entity_id. The integration owns that contract: a
websocket command resolves role -> entity_id SERVER-SIDE from the entity
registry by unique_id (the true identity the integration owns). Renames of the
display entity_id therefore never break the card (the issue #12 scenario).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState

from ec_weather.const import CONF_CITY_CODE, CONF_CITY_NAME, DOMAIN
from ec_weather.websocket import CARD_ROLES, websocket_get_entities

CITY_CODE = "on-118"
CITY_NAME = "Ottawa"


def _make_entry(
    entry_id: str,
    city_code: str = CITY_CODE,
    city_name: str = CITY_NAME,
    state: ConfigEntryState = ConfigEntryState.LOADED,
) -> MagicMock:
    """Build a mock config entry for the ec_weather domain."""
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.state = state
    entry.data = {CONF_CITY_CODE: city_code, CONF_CITY_NAME: city_name}
    return entry


def _make_hass(entries: list[MagicMock]) -> MagicMock:
    """Build a mock hass whose config_entries returns the given entries."""
    hass = MagicMock()
    hass.config_entries.async_entries.return_value = entries
    return hass


def _default_entity_registry() -> MagicMock:
    """Registry that resolves every unique_id to <domain>.<unique_id>."""
    registry = MagicMock()
    registry.async_get_entity_id.side_effect = (
        lambda domain, platform, unique_id: f"{domain}.{unique_id}"
    )
    return registry


def _device_registry(device_id: str | None = "device-abc") -> MagicMock:
    registry = MagicMock()
    device = MagicMock()
    device.id = device_id
    registry.async_get_device.return_value = device if device_id else None
    return registry


def _invoke(hass, entity_registry, device_registry=None):
    """Call the sync callback handler with patched registries; return payload."""
    if device_registry is None:
        device_registry = _device_registry()
    connection = MagicMock()
    msg = {"id": 7, "type": "ec_weather/entities"}
    with patch(
        "ec_weather.websocket.er.async_get", return_value=entity_registry
    ), patch(
        "ec_weather.websocket.dr.async_get", return_value=device_registry
    ):
        websocket_get_entities(hass, connection, msg)
    assert connection.send_result.call_count == 1
    call_msg_id, payload = connection.send_result.call_args.args
    assert call_msg_id == 7
    return payload


# ---------------------------------------------------------------------------
# Per-entry results
# ---------------------------------------------------------------------------

class TestEntrySelection:
    def test_one_item_per_loaded_entry(self):
        entries = [
            _make_entry("entry-1", "on-118", "Ottawa"),
            _make_entry("entry-2", "qc-68", "Saint-Jerome"),
        ]
        payload = _invoke(_make_hass(entries), _default_entity_registry())
        assert [item["entry_id"] for item in payload["entries"]] == [
            "entry-1",
            "entry-2",
        ]

    def test_not_loaded_entry_skipped(self):
        entries = [
            _make_entry("loaded-entry", state=ConfigEntryState.LOADED),
            _make_entry("setup-error", state=ConfigEntryState.SETUP_ERROR),
            _make_entry("not-loaded", state=ConfigEntryState.NOT_LOADED),
        ]
        payload = _invoke(_make_hass(entries), _default_entity_registry())
        assert [item["entry_id"] for item in payload["entries"]] == ["loaded-entry"]

    def test_only_ec_weather_entries_queried(self):
        hass = _make_hass([_make_entry("entry-1")])
        _invoke(hass, _default_entity_registry())
        hass.config_entries.async_entries.assert_called_once_with(DOMAIN)


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------

class TestResponseShape:
    def test_item_carries_entry_id_device_id_city_name_roles(self):
        payload = _invoke(
            _make_hass([_make_entry("entry-1")]),
            _default_entity_registry(),
            _device_registry("device-xyz"),
        )
        item = payload["entries"][0]
        assert item["entry_id"] == "entry-1"
        assert item["device_id"] == "device-xyz"
        assert item["city_name"] == CITY_NAME
        assert isinstance(item["roles"], dict)

    def test_device_id_none_when_no_device(self):
        payload = _invoke(
            _make_hass([_make_entry("entry-1")]),
            _default_entity_registry(),
            _device_registry(None),
        )
        assert payload["entries"][0]["device_id"] is None

    def test_device_looked_up_by_domain_identifier(self):
        device_registry = _device_registry("device-xyz")
        _invoke(
            _make_hass([_make_entry("entry-1", city_code=CITY_CODE)]),
            _default_entity_registry(),
            device_registry,
        )
        device_registry.async_get_device.assert_called_once_with(
            identifiers={(DOMAIN, CITY_CODE)}
        )


# ---------------------------------------------------------------------------
# Role resolution
# ---------------------------------------------------------------------------

class TestRoleResolution:
    @pytest.mark.parametrize("role", sorted(CARD_ROLES), ids=lambda role: role)
    def test_role_resolved_by_unique_id_triple(self, role):
        domain, slug = CARD_ROLES[role]
        registry = _default_entity_registry()
        payload = _invoke(_make_hass([_make_entry("entry-1")]), registry)
        expected_unique_id = f"{slug}_{CITY_CODE}"
        registry.async_get_entity_id.assert_any_call(
            domain, DOMAIN, expected_unique_id
        )
        roles = payload["entries"][0]["roles"]
        assert roles[role] == f"{domain}.{expected_unique_id}"

    def test_renamed_entity_id_returned_verbatim(self):
        """Issue #12: the registry returns a user-renamed id -> carried as-is."""
        registry = MagicMock()

        def _resolve(domain, platform, unique_id):
            if unique_id == f"ec_temperature_{CITY_CODE}":
                return "sensor.my_custom_outdoor_temp"
            return f"{domain}.{unique_id}"

        registry.async_get_entity_id.side_effect = _resolve
        payload = _invoke(_make_hass([_make_entry("entry-1")]), registry)
        assert (
            payload["entries"][0]["roles"]["temperature"]
            == "sensor.my_custom_outdoor_temp"
        )

    def test_missing_entity_role_omitted(self):
        """A role whose entity is not in the registry is dropped, not errored."""
        registry = MagicMock()

        def _resolve(domain, platform, unique_id):
            if unique_id.startswith("ec_yesterday_"):
                return None
            return f"{domain}.{unique_id}"

        registry.async_get_entity_id.side_effect = _resolve
        payload = _invoke(_make_hass([_make_entry("entry-1")]), registry)
        roles = payload["entries"][0]["roles"]
        assert "yesterday_rain" not in roles
        assert "yesterday_snow" not in roles
        assert "yesterday_precipitation" not in roles
        # Present roles still resolve.
        assert roles["temperature"] == f"sensor.ec_temperature_{CITY_CODE}"

    def test_alert_active_role_uses_binary_sensor_domain(self):
        assert CARD_ROLES["alert_active"] == ("binary_sensor", "ec_alert_active")

    def test_air_quality_role_uses_aqhi_slug(self):
        assert CARD_ROLES["air_quality"] == ("sensor", "ec_aqhi")
