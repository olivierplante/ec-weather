"""ECAQHICoordinator — 30-minute AQHI update."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_AQHI_LOCATION_ID,
    CONF_LAT,
    CONF_LON,
    DEFAULT_AQHI_INTERVAL,
    DOMAIN,
    EC_API_BASE,
    REQUEST_TIMEOUT,
    aqhi_risk_level,
)
from ..api_client import discover_aqhi_station, fetch_json_with_retry
from ..utils import safe_float
from .base import OnDemandCoordinator

_LOGGER = logging.getLogger(__name__)

# Self-heal a dead/retired AQHI station at most once per this window. A station
# id can retire or be renumbered by EC; the collection then returns a
# well-formed response with zero features forever. We re-run discovery, but
# strictly rate-limited so a permanently dead station costs at most one extra
# EC query per day (a reboot resets the in-memory clock and may retry once
# early — acceptable, see the discovery spec).
REDISCOVERY_INTERVAL = timedelta(hours=24)


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
        entry: ConfigEntry | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_aqhi",
            interval=timedelta(minutes=interval_minutes),
            polling=polling,
        )
        self.aqhi_location_id = aqhi_location_id
        # The config entry is needed to self-heal a dead station: read the
        # city's lat/lon for re-discovery and persist a replacement id.
        self._entry = entry
        # In-memory 24h rate-limit clock for station re-discovery. Reset on
        # reboot by design (a fresh process may retry once early).
        self._last_rediscovery_attempt: datetime | None = None

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

        raw_features = data.get("features")
        well_formed_empty = isinstance(raw_features, list) and not raw_features
        if not isinstance(raw_features, list):
            _LOGGER.warning(
                "EC AQHI: unexpected API response — features is not a list"
            )
            features = []
        else:
            features = raw_features
        if not features:
            _LOGGER.debug("EC AQHI: no forecasts returned for %s", self.aqhi_location_id)
            # A well-formed empty response means the configured station is dead
            # (retired or renumbered). Malformed bodies do NOT count.
            if well_formed_empty:
                await self._maybe_rediscover_station()
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

    async def _maybe_rediscover_station(self) -> None:
        """Re-run station discovery when the configured station returns nothing.

        Rate-limited to one attempt per ``REDISCOVERY_INTERVAL`` (tracked in
        memory). If discovery finds a DIFFERENT station near the city, the
        config entry is updated and this coordinator adopts the new id in
        place — the integration registers no update listener, so it does not
        reload and the next poll must use the new station directly. Discovery
        returning nothing or the same id is a silent no-op.
        """
        if self._entry is None:
            return

        now = dt_util.utcnow()
        if (
            self._last_rediscovery_attempt is not None
            and now - self._last_rediscovery_attempt < REDISCOVERY_INTERVAL
        ):
            return
        # Count the attempt even if it fails, so a permanently dead station
        # costs at most one extra EC query per window.
        self._last_rediscovery_attempt = now

        lat = self._entry.data.get(CONF_LAT)
        lon = self._entry.data.get(CONF_LON)
        if lat is None or lon is None:
            _LOGGER.debug("EC AQHI: cannot re-discover station — entry has no lat/lon")
            return

        session = async_get_clientsession(self.hass)
        new_location_id = await discover_aqhi_station(
            session,
            lat=lat,
            lon=lon,
            api_base=EC_API_BASE,
            timeout=REQUEST_TIMEOUT,
        )

        if not new_location_id or new_location_id == self.aqhi_location_id:
            _LOGGER.debug(
                "EC AQHI: re-discovery found no replacement for station %s",
                self.aqhi_location_id,
            )
            return

        old_location_id = self.aqhi_location_id
        _LOGGER.info(
            "EC AQHI: station %s returned no data; re-discovered station %s "
            "near the configured location — updating config",
            old_location_id,
            new_location_id,
        )
        self.aqhi_location_id = new_location_id
        self.hass.config_entries.async_update_entry(
            self._entry,
            data={**self._entry.data, CONF_AQHI_LOCATION_ID: new_location_id},
        )
