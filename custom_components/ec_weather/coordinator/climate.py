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
from datetime import date, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..api_client import fetch_json_with_retry
from ..const import DOMAIN, EC_API_BASE, SCAN_INTERVAL_CLIMATE
from ..utils import safe_float
from .base import OnDemandCoordinator

_LOGGER = logging.getLogger(__name__)


def parse_climate_response(data: dict, station_type: str) -> dict:
    """Parse a climate-daily API response into yesterday's precipitation.

    Pure function — no HA dependencies. ``station_type`` is "split" or
    "combined" and is echoed back so consumers can branch their display
    without re-deriving it.

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

    props = features[0].get("properties") if features else None
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


class ECClimateCoordinator(OnDemandCoordinator):
    """Fetches yesterday's observed precipitation for one climate station.

    Yesterday's data is typically published after ~06:00 local time. Until
    it arrives the coordinator returns published=False and retries on the
    scheduled interval (every 30 min). Once yesterday is published it caches
    the result and skips re-fetching for the rest of the day.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        station_id: str | None,
        station_type: str = "combined",
        station_name: str | None = None,
        distance_km: float | None = None,
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

    async def _do_update(self) -> dict:
        if not self.station_id:
            _LOGGER.debug("EC climate: no precipitation station configured")
            return self._unconfigured()

        yesterday = (date.today() - timedelta(days=1)).isoformat()

        # Already have yesterday's published data — don't re-fetch.
        if (
            self._published_date == yesterday
            and self.data
            and self.data.get("published")
        ):
            return self.data

        url = (
            f"{EC_API_BASE}/collections/climate-daily/items"
            f"?CLIMATE_IDENTIFIER={self.station_id}&datetime={yesterday}&f=json"
        )
        session = async_get_clientsession(self.hass)
        data = await fetch_json_with_retry(session, url, label="climate")

        parsed = parse_climate_response(data, self.station_type)
        parsed["available"] = True
        parsed["station_name"] = self.station_name
        parsed["distance_km"] = self.distance_km

        if parsed["published"]:
            self._published_date = yesterday
            _LOGGER.debug("EC climate: yesterday (%s) published", yesterday)
        else:
            self._published_date = None
            _LOGGER.debug("EC climate: yesterday (%s) not published yet", yesterday)

        return parsed
