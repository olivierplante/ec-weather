"""ECAlertCoordinator — 30-minute alert update."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..api_client import FetchError, fetch_json_with_retry
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


def prune_retained_alerts(retained: dict, now: datetime | None = None) -> dict:
    """Prune expired alerts from a retained (last-known-good) payload.

    Used when an alerts refresh fails transiently but prior good data exists.
    Retention is naturally bounded by each alert's EC-declared expiration: an
    alert is dropped once its ``expires`` timestamp has passed, so a stale
    payload never outlives EC's own validity window. count / highest_type are
    recomputed over the survivors, and ``stale`` is flagged True. An all-expired
    retention collapses to the honest empty state (count 0, highest None) rather
    than serving stale garbage.

    Pure function — no HA dependencies.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    surviving: list[dict] = []
    for alert in retained.get("alerts") or []:
        expires_str = alert.get("expires")
        if expires_str:
            try:
                expires = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
                if expires <= now:
                    continue
            except ValueError:
                pass
        surviving.append(alert)

    highest_type: str | None = None
    for alert_type in _ALERT_TYPE_PRIORITY:
        if any(alert.get("type") == alert_type for alert in surviving):
            highest_type = alert_type
            break

    return {
        "alert_count": len(surviving),
        "alerts": surviving,
        "highest_type": highest_type,
        "stale": True,
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
        # Timestamp of the last SUCCESSFUL fetch — drives the retention age in
        # the "serving retained" log line. None until the first success.
        self._last_success_dt: datetime | None = None
        # True while we are serving last-known-good data through a failure run,
        # so the INFO line is logged once per outage, then downgraded to debug.
        self._serving_retained = False

    async def _do_update(self) -> dict:
        url = (
            f"{EC_API_BASE}/collections/weather-alerts/items"
            f"?bbox={self.bbox}&f=json&skipGeometry=true"
        )
        session = async_get_clientsession(self.hass)
        try:
            data = await fetch_json_with_retry(
                session, url, label="alerts",
            )
        except FetchError:
            # Transient fetch failure. If we hold last-known-good data, keep it
            # (pruned to each alert's EC expiration) instead of dropping to
            # unknown — the alert bar must not blank during an active alert.
            retained = self.data
            if not isinstance(retained, dict) or "alerts" not in retained:
                # First-ever fetch failing: nothing to retain. Propagate so the
                # entities go unknown — never fabricate an alert state.
                raise
            return self._serve_retained(retained)

        result = parse_alert_response(data, self.language)
        # A successful fetch replaces retained data entirely (result carries no
        # ``stale`` key) and clears the outage-logging latch.
        self._last_success_dt = datetime.now(timezone.utc)
        self._serving_retained = False
        _LOGGER.debug(
            "EC alerts updated: %d active, highest=%s",
            result["alert_count"], result["highest_type"],
        )
        return result

    def _serve_retained(self, retained: dict) -> dict:
        """Return the retained payload pruned to live alerts, and log once."""
        now = datetime.now(timezone.utc)
        pruned = prune_retained_alerts(retained, now)

        if self._last_success_dt is not None:
            age_min = (now - self._last_success_dt).total_seconds() / 60
            age_str = f"{age_min:.0f} min"
        else:
            age_str = "unknown time"

        if not self._serving_retained:
            self._serving_retained = True
            _LOGGER.info(
                "EC alerts fetch failed; serving %d retained alert(s) "
                "(last success %s ago, pruned to EC expirations)",
                pruned["alert_count"], age_str,
            )
        else:
            _LOGGER.debug(
                "EC alerts fetch failed again; still serving %d retained "
                "alert(s) (last success %s ago)",
                pruned["alert_count"], age_str,
            )
        return pruned
