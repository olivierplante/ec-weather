"""ECClimateCoordinator — yesterday's observed precipitation (issue #9).

Fetches yesterday's daily climate observation from EC's ``climate-daily``
collection for a single configured station. Two station kinds exist:

- ``split``: reports TOTAL_RAIN (mm) + TOTAL_SNOW (cm) separately, plus
  TOTAL_PRECIPITATION (mm water-equivalent).
- ``combined``: reports only TOTAL_PRECIPITATION; rain/snow are always null.

Honesty rules (see parse_climate_response):
- ``null`` total (or missing row) = "not published yet" → published=False.
- ``0`` total = measured dry day → published=True, value 0.
These must never be conflated: a dry day is not the same as missing data.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from ..api_client import discover_precip_stations, fetch_json_with_retry
from ..const import (
    CONF_LAT,
    CONF_LON,
    CONF_PRECIP_STATION_DISTANCE_KM,
    CONF_PRECIP_STATION_ID,
    CONF_PRECIP_STATION_NAME,
    CONF_PRECIP_STATION_TYPE,
    DOMAIN,
    EC_API_BASE,
    PRECIP_STALE_THRESHOLD_DAYS,
    PRECIP_STALENESS_LOOKBACK_DAYS,
    REQUEST_TIMEOUT,
    SCAN_INTERVAL_CLIMATE,
)
from ..utils import safe_float
from .base import OnDemandCoordinator

_LOGGER = logging.getLogger(__name__)

# Self-heal a lagging precip station at most once per this window — mirrors
# ECAQHICoordinator.REDISCOVERY_INTERVAL. A station can qualify at onboarding
# on old-but-non-null data and then sit behind an EC-wide publication
# backlog forever with no re-evaluation; re-running discovery is rate-limited
# so a permanently-lagging station costs at most one extra EC query per day
# (a reboot resets the in-memory clock and may retry once early — acceptable,
# same tradeoff AQHI makes).
REDISCOVERY_INTERVAL = timedelta(hours=24)


def parse_climate_response(
    data: dict, station_type: str, target_date: str | None = None
) -> dict:
    """Parse a climate-daily API response into one day's precipitation.

    Pure function — no HA dependencies. ``station_type`` is "split" or
    "combined" and is echoed back so consumers can branch their display
    without re-deriving it. ``target_date`` (ISO date) selects which row to
    parse out of a possibly-multi-row (windowed) response by matching
    LOCAL_DATE; when omitted (the legacy default), the first feature is used
    — correct for the original single-date query shape.

    Returns a dict with:
      published: bool   — True only if a row exists AND total is not null
      total_mm: float | None
      rain_mm: float | None   — always None for combined stations
      snow_cm: float | None   — always None for combined stations
      station_type: str
    """
    features = data.get("features") or []
    if not isinstance(features, list):
        features = []

    if target_date is None:
        props = features[0].get("properties") if features else None
    else:
        props = None
        for feature in features:
            candidate = feature.get("properties") or {}
            local_date = candidate.get("LOCAL_DATE")
            row_date = local_date[:10] if isinstance(local_date, str) else None
            if row_date == target_date:
                props = candidate
                break
    props = props or {}

    total_mm = safe_float(props.get("TOTAL_PRECIPITATION"))

    if station_type == "split":
        rain_mm = safe_float(props.get("TOTAL_RAIN"))
        snow_cm = safe_float(props.get("TOTAL_SNOW"))
    else:
        # Combined stations never report a rain/snow breakdown.
        rain_mm = None
        snow_cm = None

    # "Published" is driven solely by the combined total being present.
    # A real 0 counts as published (measured dry day); null/missing does not.
    published = total_mm is not None

    return {
        "published": published,
        "total_mm": total_mm,
        "rain_mm": rain_mm,
        "snow_cm": snow_cm,
        "station_type": station_type,
    }


def latest_precip_date(data: dict) -> str | None:
    """Return the most recent LOCAL_DATE with non-null TOTAL_PRECIPITATION.

    Pure function over a windowed climate-daily response for a SINGLE
    station (the coordinator's request is filtered to one CLIMATE_IDENTIFIER,
    unlike parse_precip_stations' multi-station discovery response). Returns
    an ISO date string, or None when nothing in the window has published yet.
    """
    features = data.get("features") or []
    if not isinstance(features, list):
        features = []

    latest: str | None = None
    for feature in features:
        props = feature.get("properties") or {}
        if safe_float(props.get("TOTAL_PRECIPITATION")) is None:
            continue
        local_date = props.get("LOCAL_DATE")
        row_date = local_date[:10] if isinstance(local_date, str) else None
        if row_date and (latest is None or row_date > latest):
            latest = row_date
    return latest


class ECClimateCoordinator(OnDemandCoordinator):
    """Fetches yesterday's observed precipitation for one climate station.

    Yesterday's data is typically published after ~06:00 local time. Until
    it arrives the coordinator returns published=False and retries on the
    scheduled interval (every 30 min). Once yesterday is published it caches
    the result and skips re-fetching for the rest of the day.

    Self-heal: onboarding discovery can pick a station that later falls
    behind an EC-wide publication backlog with no re-evaluation. Every fetch
    widens its query to a window (see PRECIP_STALENESS_LOOKBACK_DAYS) instead
    of just yesterday, so the SAME request also reveals the station's most
    recently published date — no extra API call needed. When that date is
    PRECIP_STALE_THRESHOLD_DAYS old or older, _maybe_rediscover_station runs,
    mirroring ECAQHICoordinator._maybe_rediscover_station.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        station_id: str | None,
        station_type: str = "combined",
        station_name: str | None = None,
        distance_km: float | None = None,
        entry: ConfigEntry | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_climate",
            interval=SCAN_INTERVAL_CLIMATE,
            polling=station_id is not None,
        )
        self.station_id = station_id
        self.station_type = station_type
        self.station_name = station_name
        self.distance_km = distance_km
        self._published_date: str | None = None
        # The config entry is needed to self-heal a lagging station: read the
        # user's lat/lon for re-discovery and persist a replacement.
        self._entry = entry
        # In-memory 24h rate-limit clock for station re-discovery. Reset on
        # reboot by design (a fresh process may retry once early).
        self._last_rediscovery_attempt: datetime | None = None

    def _unconfigured(self) -> dict:
        return {
            "available": False,
            "published": False,
            "total_mm": None,
            "rain_mm": None,
            "snow_cm": None,
            "station_type": self.station_type,
            "station_name": self.station_name,
            "distance_km": self.distance_km,
        }

    def _build_url(self, window_start: date, window_end: date) -> str:
        return (
            f"{EC_API_BASE}/collections/climate-daily/items"
            f"?CLIMATE_IDENTIFIER={self.station_id}"
            f"&datetime={window_start.isoformat()}/{window_end.isoformat()}"
            f"&f=json&properties=LOCAL_DATE,TOTAL_PRECIPITATION,TOTAL_RAIN,TOTAL_SNOW"
        )

    async def _do_update(self) -> dict:
        if not self.station_id:
            _LOGGER.debug("EC climate: no precipitation station configured")
            return self._unconfigured()

        yesterday_date = date.today() - timedelta(days=1)
        yesterday = yesterday_date.isoformat()

        # Already have yesterday's published data — don't re-fetch.
        if (
            self._published_date == yesterday
            and self.data
            and self.data.get("published")
        ):
            return self.data

        # Widen the query to a lookback window (not just yesterday) so this
        # single request also reveals the station's most recently published
        # date, needed for the staleness check below.
        window_start = yesterday_date - timedelta(days=PRECIP_STALENESS_LOOKBACK_DAYS)
        url = self._build_url(window_start, yesterday_date)
        session = async_get_clientsession(self.hass)
        data = await fetch_json_with_retry(session, url, label="climate")

        parsed = parse_climate_response(data, self.station_type, target_date=yesterday)
        parsed["available"] = True
        parsed["station_name"] = self.station_name
        parsed["distance_km"] = self.distance_km

        if parsed["published"]:
            self._published_date = yesterday
            _LOGGER.debug("EC climate: yesterday (%s) published", yesterday)
        else:
            self._published_date = None
            _LOGGER.debug("EC climate: yesterday (%s) not published yet", yesterday)

        # This coordinator polls every SCAN_INTERVAL_CLIMATE whenever a
        # station is configured (unlike AQHI's minimal-mode on-demand
        # polling), so a healed station is simply picked up on the next
        # scheduled poll — no same-cycle retry is needed here.
        latest_published = latest_precip_date(data)
        if self._is_stale(latest_published):
            await self._maybe_rediscover_station(latest_published)

        return parsed

    def _is_stale(self, latest_published_date: str | None) -> bool:
        """True when the station's most recent published value is lagging.

        ``None`` (nothing published anywhere in the lookback window) counts
        as stale — that's a worse signal than any single old date.
        """
        if latest_published_date is None:
            return True
        try:
            latest = date.fromisoformat(latest_published_date)
        except ValueError:
            return False
        return (date.today() - latest).days >= PRECIP_STALE_THRESHOLD_DAYS

    async def _maybe_rediscover_station(self, latest_published_date: str | None) -> bool:
        """Re-run precip-station discovery when the configured station lags.

        Rate-limited to one attempt per ``REDISCOVERY_INTERVAL`` (tracked in
        memory) — mirrors ECAQHICoordinator._maybe_rediscover_station.
        Adopts a replacement ONLY when discovery finds a candidate — of the
        SAME station_type the user has configured (nearest_split for a split
        install, nearest for combined) — whose latest_precip_date is
        STRICTLY newer than the currently configured station's. An
        equal-or-older candidate is not an improvement: EC-wide backlogs
        commonly mean nothing nearby is any fresher, and adopting sideways
        would just relocate the same problem. Persists to the config entry
        in place — no reload is wired for this integration, so the next
        fetch must use the new station directly.

        Returns True when a different, strictly-fresher station was adopted.
        """
        if self._entry is None:
            return False

        now = dt_util.utcnow()
        if (
            self._last_rediscovery_attempt is not None
            and now - self._last_rediscovery_attempt < REDISCOVERY_INTERVAL
        ):
            return False
        # Count the attempt even if it fails, so a permanently lagging
        # station costs at most one extra EC query per window.
        self._last_rediscovery_attempt = now

        lat = self._entry.data.get(CONF_LAT)
        lon = self._entry.data.get(CONF_LON)
        if lat is None or lon is None:
            _LOGGER.debug("EC climate: cannot re-discover station — entry has no lat/lon")
            return False

        session = async_get_clientsession(self.hass)
        discovered = await discover_precip_stations(
            session,
            lat=lat,
            lon=lon,
            api_base=EC_API_BASE,
            timeout=REQUEST_TIMEOUT,
        )
        candidate = (
            discovered.get("nearest_split")
            if self.station_type == "split"
            else discovered.get("nearest")
        )
        if candidate is None:
            _LOGGER.debug("EC climate: re-discovery found no candidate station")
            return False

        candidate_date = candidate.get("latest_precip_date")
        if candidate_date is None or (
            latest_published_date is not None and candidate_date <= latest_published_date
        ):
            _LOGGER.debug(
                "EC climate: re-discovered candidate %s is not fresher than "
                "current station %s — not adopting",
                candidate.get("station_id"),
                self.station_id,
            )
            return False

        old_station_id = self.station_id
        _LOGGER.info(
            "EC climate: station %s is lagging (latest published %s); "
            "re-discovered fresher station %s (latest %s) — updating config",
            old_station_id,
            latest_published_date,
            candidate["station_id"],
            candidate_date,
        )
        self.station_id = candidate["station_id"]
        self.station_type = candidate["type"]
        self.station_name = candidate["name"]
        self.distance_km = candidate["distance_km"]
        self.hass.config_entries.async_update_entry(
            self._entry,
            data={
                **self._entry.data,
                CONF_PRECIP_STATION_ID: self.station_id,
                CONF_PRECIP_STATION_TYPE: self.station_type,
                CONF_PRECIP_STATION_NAME: self.station_name,
                CONF_PRECIP_STATION_DISTANCE_KM: self.distance_km,
            },
        )
        return True
