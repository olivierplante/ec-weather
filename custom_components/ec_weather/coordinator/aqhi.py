"""ECAQHICoordinator — 30-minute AQHI update."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..const import (
    DEFAULT_AQHI_INTERVAL,
    DOMAIN,
    EC_API_BASE,
    aqhi_risk_level,
)
from ..api_client import fetch_json_with_retry
from ..utils import safe_float
from .base import OnDemandCoordinator

_LOGGER = logging.getLogger(__name__)


class ECAQHICoordinator(OnDemandCoordinator):
    """Fetches AQHI forecasts for the configured station.

    EC publishes hourly AQHI forecasts 4x/day. This coordinator picks
    the current-hour forecast from the most recent publication, which is
    equivalent to what EC's own AirHealth website displays.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        aqhi_location_id: str | None,
        interval_minutes: int = DEFAULT_AQHI_INTERVAL,
        polling: bool = False,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_aqhi",
            interval=timedelta(minutes=interval_minutes),
            polling=polling,
        )
        self.aqhi_location_id = aqhi_location_id

    async def _do_update(self) -> dict:
        if not self.aqhi_location_id:
            _LOGGER.debug("EC AQHI: no AQHI station configured")
            return {"aqhi": None, "risk_level": None, "forecast_datetime": None}

        if self.is_fresh():
            return self.data

        # Fetch upcoming forecasts — filter server-side to reduce payload
        now_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        now_hour_iso = now_hour.strftime("%Y-%m-%dT%H:%M:%SZ")
        url = (
            f"{EC_API_BASE}/collections/aqhi-forecasts-realtime/items"
            f"?location_id={self.aqhi_location_id}&f=json&limit=24"
            f"&sortby=forecast_datetime&skipGeometry=true"
            f"&datetime={now_hour_iso}/.."
            f"&properties=aqhi,forecast_datetime,publication_datetime"
        )
        session = async_get_clientsession(self.hass)
        data = await fetch_json_with_retry(
            session, url, label="AQHI",
        )

        features = data.get("features") or []
        if not isinstance(features, list):
            _LOGGER.warning(
                "EC AQHI: unexpected API response — features is not a list"
            )
            features = []
        if not features:
            _LOGGER.debug("EC AQHI: no forecasts returned for %s", self.aqhi_location_id)
            return {"aqhi": None, "risk_level": None, "forecast_datetime": None}

        # Find the current-hour forecast from the most recent publication.
        # Multiple publications exist per forecast_datetime — pick the latest pub.
        candidates: list[tuple[float, float, dict]] = []

        for feature in features:
            props = feature.get("properties") or {}
            fdt_str = props.get("forecast_datetime", "")
            pub_str = props.get("publication_datetime", "")
            try:
                fdt = datetime.fromisoformat(fdt_str.replace("Z", "+00:00"))
                pub = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            if fdt >= now_hour:
                # Sort key: latest publication first, then earliest forecast_datetime
                candidates.append((-pub.timestamp(), fdt.timestamp(), props))

        if not candidates:
            _LOGGER.debug("EC AQHI: no current-or-future forecast found")
            return {"aqhi": None, "risk_level": None, "forecast_datetime": None}

        candidates.sort(key=lambda x: (x[0], x[1]))
        best = candidates[0][2]

        aqhi = safe_float(best.get("aqhi"))
        risk_level = aqhi_risk_level(aqhi)

        _LOGGER.debug(
            "EC AQHI updated: forecast_datetime=%s aqhi=%s risk=%s",
            best.get("forecast_datetime"),
            aqhi,
            risk_level,
        )

        self.mark_refreshed()
        return {
            "aqhi": aqhi,
            "risk_level": risk_level,
            "forecast_datetime": best.get("forecast_datetime"),
        }
