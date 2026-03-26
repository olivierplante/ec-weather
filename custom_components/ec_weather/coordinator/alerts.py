"""ECAlertCoordinator — 30-minute alert update."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..api_client import fetch_json_with_retry
from ..const import DEFAULT_LANGUAGE, DOMAIN, EC_API_BASE, SCAN_INTERVAL_ALERTS
from .base import OnDemandCoordinator

_LOGGER = logging.getLogger(__name__)

# Priority order for determining "highest" alert type
_ALERT_TYPE_PRIORITY = ["warning", "watch", "advisory", "statement"]


def parse_alert_response(data: dict, language: str = "en") -> dict:
    """Parse an EC alerts API response into alert count, list, and highest type.

    Pure function — no HA dependencies. Testable without a hass instance.
    """
    features = data.get("features") or []
    if not isinstance(features, list):
        features = []

    now = datetime.now(timezone.utc)

    active: list[dict] = []
    for feature in features:
        props = feature.get("properties") or {}

        # Skip cancelled alerts
        status = props.get("status_en", "")
        if status == "cancelled":
            continue

        # Skip expired alerts
        expires_str = props.get("expiration_datetime")
        if expires_str:
            try:
                expires = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
                if expires <= now:
                    continue
            except ValueError:
                pass

        headline = (
            props.get(f"alert_name_{language}")
            or props.get("alert_name_en")
            or ""
        )
        text = props.get(f"alert_text_{language}") or props.get("alert_text_en") or ""

        # Skip alerts with no text content (EC sometimes publishes empty alerts)
        if not text.strip():
            continue

        active.append({
            "headline": headline,
            "type": props.get("alert_type", ""),
            "expires": expires_str,
            "text": text,
        })

    # Deduplicate alerts (EC API returns one per sub-zone)
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for alert in active:
        key = (alert["headline"], alert["text"])
        if key not in seen:
            seen.add(key)
            unique.append(alert)
    active = unique

    # Determine the highest-priority alert type present
    highest_type: str | None = None
    for alert_type in _ALERT_TYPE_PRIORITY:
        if any(alert["type"] == alert_type for alert in active):
            highest_type = alert_type
            break

    return {
        "alert_count": len(active),
        "alerts": active,
        "highest_type": highest_type,
    }


class ECAlertCoordinator(OnDemandCoordinator):
    """Fetches active weather alerts for the configured bounding box."""

    def __init__(
        self, hass: HomeAssistant, bbox: str, language: str = DEFAULT_LANGUAGE
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_alerts",
            interval=SCAN_INTERVAL_ALERTS,
            polling=True,  # alerts always poll in all modes
        )
        self.bbox = bbox
        self.language = language

    async def _do_update(self) -> dict:
        url = (
            f"{EC_API_BASE}/collections/weather-alerts/items"
            f"?bbox={self.bbox}&f=json&skipGeometry=true"
        )
        session = async_get_clientsession(self.hass)
        data = await fetch_json_with_retry(
            session, url, label="alerts",
        )
        result = parse_alert_response(data, self.language)
        _LOGGER.debug(
            "EC alerts updated: %d active, highest=%s",
            result["alert_count"], result["highest_type"],
        )
        return result
