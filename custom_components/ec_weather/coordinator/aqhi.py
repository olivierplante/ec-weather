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
from ..api_client import AqhiDiscoveryError, discover_aqhi_station, fetch_json_with_retry
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

        result, needs_rediscovery = await self._fetch_and_parse(self.aqhi_location_id)
        if needs_rediscovery:
            adopted_new_station = await self._maybe_rediscover_station()
            if adopted_new_station:
                # Minimal mode never polls again after startup, so a healed
                # station must be usable from THIS cycle's result — retry
                # once with the new id. If that retry also comes up empty,
                # fall through to the None shape as before; either way this
                # is a single retry, not a loop back into rediscovery.
                result, _ = await self._fetch_and_parse(self.aqhi_location_id)
        return result

    async def _fetch_and_parse(self, location_id: str) -> tuple[dict, bool]:
        """Fetch and parse one AQHI forecast page for ``location_id``.

        Returns ``(result, needs_rediscovery)``. ``result`` is either the
        parsed aqhi/risk_level/forecast_datetime dict or the None shape.
        ``needs_rediscovery`` is True when the response indicates the
        station itself is dead: a well-formed empty features list, or a
        non-empty list where nothing clears the current-hour filter. A
        malformed body (features not a list) does NOT count — that's an API
        problem, not evidence the station is retired.
        """
        # EC's datetime= filter no longer matches rows on this collection for
        # a healthy station (Sept 2026: it appears publication-based, not
        # forecast_datetime-based, and returns numberMatched: 0 even for a
        # fresh publication) — the current-hour filter runs entirely
        # client-side below via the candidate loop instead. Sorted
        # newest-forecast-first with limit=48 so the latest publication's
        # ~36h of rows are comfortably covered.
        now_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        url = (
            f"{EC_API_BASE}/collections/aqhi-forecasts-realtime/items"
            f"?location_id={location_id}&f=json&limit=48"
            f"&sortby=-forecast_datetime&skipGeometry=true"
            f"&properties=aqhi,forecast_datetime,publication_datetime"
        )
        session = async_get_clientsession(self.hass)
        data = await fetch_json_with_retry(
            session, url, label="AQHI",
        )

        none_shape = {"aqhi": None, "risk_level": None, "forecast_datetime": None}

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
            _LOGGER.debug("EC AQHI: no forecasts returned for %s", location_id)
            # A well-formed empty response means the configured station is dead
            # (retired or renumbered). Malformed bodies do NOT count.
            return none_shape, well_formed_empty

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
            # Non-empty features but nothing current-or-future is the same
            # dead/stale-station signal as a well-formed empty list — a
            # half-dead station must not stick forever either.
            return none_shape, True

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
        }, False

    async def _maybe_rediscover_station(self) -> bool:
        """Re-run station discovery when the configured station returns nothing.

        Rate-limited to one attempt per ``REDISCOVERY_INTERVAL`` (tracked in
        memory). If discovery finds a DIFFERENT station near the city, the
        config entry is updated and this coordinator adopts the new id in
        place — the integration registers no update listener, so it does not
        reload and the next poll must use the new station directly. Discovery
        returning nothing or the same id is a silent no-op.

        Returns True when a different station id was actually adopted, so
        the caller can decide whether to retry the fetch within this same
        update cycle.

        A discovery request that FAILS (AqhiDiscoveryError — network error,
        timeout, or bad JSON) never ANSWERED, so it must NOT burn the 24h
        window: a boot-time network transient would otherwise strand a
        healthy station without self-heal until the next restart, since
        minimal polling mode never fetches AQHI again on its own. Only a
        discovery that actually answers — a replacement, the same id, or
        nothing found — counts as the attempt.
        """
        if self._entry is None:
            return False

        now = dt_util.utcnow()
        if (
            self._last_rediscovery_attempt is not None
            and now - self._last_rediscovery_attempt < REDISCOVERY_INTERVAL
        ):
            return False

        lat = self._entry.data.get(CONF_LAT)
        lon = self._entry.data.get(CONF_LON)
        if lat is None or lon is None:
            _LOGGER.debug("EC AQHI: cannot re-discover station — entry has no lat/lon")
            self._last_rediscovery_attempt = now
            return False

        session = async_get_clientsession(self.hass)
        try:
            new_location_id = await discover_aqhi_station(
                session,
                lat=lat,
                lon=lon,
                api_base=EC_API_BASE,
                timeout=REQUEST_TIMEOUT,
            )
        except AqhiDiscoveryError as err:
            _LOGGER.debug("EC AQHI: re-discovery request failed: %s", err)
            return False

        # Discovery ANSWERED (found a replacement, the same id, or nothing) —
        # count the attempt even on a "nothing found" answer, so a
        # permanently dead station costs at most one extra EC query per
        # window.
        self._last_rediscovery_attempt = now

        if not new_location_id or new_location_id == self.aqhi_location_id:
            _LOGGER.debug(
                "EC AQHI: re-discovery found no replacement for station %s",
                self.aqhi_location_id,
            )
            return False

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
        return True
