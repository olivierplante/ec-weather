"""HTTP/API client helpers for the EC Weather integration.

This module contains all outbound HTTP concerns:
- fetch_json_with_retry: generic JSON fetch with retry for transient errors
- query_geomet_feature_info: GeoMet WMS GetFeatureInfo point query
- parse_ec_city_features: parse EC city features from API response
- discover_aqhi_station: find nearest AQHI station via EC API

No Home Assistant dependencies — accepts aiohttp sessions as parameters.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any

import aiohttp

from .utils import safe_float as _safe_float

from .const import (
    FETCH_RETRIES,
    FETCH_RETRY_DELAY,
    GEOMET_BASE_URL,
    GEOMET_CRS,
    REQUEST_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

# Pattern to extract lat,lon from EC weather URL: coords=45.82,-73.96
_COORDS_RE = re.compile(r"coords=([-\d.]+),([-\d.]+)")


class FetchError(Exception):
    """Raised when an API fetch fails after retries.

    This is a plain exception with no HA dependency. Coordinators should
    catch it and re-raise as UpdateFailed for HA's DataUpdateCoordinator.
    """


class TransientGeoMetError(Exception):
    """Raised when a GeoMet query fails due to a transient network error.

    The caller (coordinator) should handle this by NOT caching the result
    and flagging for retry on next cycle.
    """


class RateLimitedError(TransientGeoMetError):
    """Raised when GeoMet answers HTTP 429 (Too Many Requests).

    A subclass of TransientGeoMetError so every ``except TransientGeoMetError``
    still refuses to cache it; the dedicated type lets the coordinator pace the
    wave with a short backoff on top of the never-cache behaviour.
    """


# ---------------------------------------------------------------------------
# Generic JSON fetch with retry
# ---------------------------------------------------------------------------

async def fetch_json_with_retry(
    session: aiohttp.ClientSession,
    url: str,
    timeout: int = REQUEST_TIMEOUT,
    retries: int = FETCH_RETRIES,
    retry_delay: int = FETCH_RETRY_DELAY,
    label: str = "data",
) -> dict:
    """Fetch JSON from a URL with retry on transient connection/DNS errors.

    Retries only on ClientConnectorError (DNS, connection refused) and
    TimeoutError. HTTP errors (4xx/5xx) and JSON parse errors are raised
    immediately since retrying won't help.
    """
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            async with asyncio.timeout(timeout):
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    return await resp.json()
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as err:
            last_err = err
            if attempt < retries:
                _LOGGER.warning(
                    "EC Weather: transient error fetching %s (attempt %d/%d, "
                    "retrying in %ds): %s",
                    label, attempt, retries, retry_delay, err,
                )
                await asyncio.sleep(retry_delay)
            else:
                _LOGGER.error(
                    "EC Weather: failed to fetch %s after %d attempts: %s",
                    label, retries, err,
                )
        except aiohttp.ClientError as err:
            raise FetchError(f"Error fetching {label}: {err}") from err
        except ValueError as err:
            raise FetchError(f"Error parsing {label} JSON: {err}") from err

    raise FetchError(
        f"Error fetching {label}: {last_err}"
    ) from last_err


# ---------------------------------------------------------------------------
# GeoMet WMS GetFeatureInfo query
# ---------------------------------------------------------------------------

def _parse_geomet_response(data: dict) -> tuple[float | None, str | None]:
    """Parse a GeoMet GetFeatureInfo JSON response.

    Returns (value, reference_datetime) where:
    - value: the numeric data value (or None if no features)
    - reference_datetime: the model run time (or None if not present)
    """
    features = data.get("features") or []
    if not features:
        return None, None

    props = features[0].get("properties", {})
    value = _safe_float(props.get("value"))
    ref_dt = props.get("reference_datetime")
    return value, ref_dt


async def query_geomet_feature_info(
    session: aiohttp.ClientSession,
    geomet_bbox: str,
    layer: str,
    timestep: datetime,
    timeout: int,
) -> tuple[float | None, str | None]:
    """Query a single WEonG layer at one UTC timestep via GeoMet WMS.

    Failure vs. no-data are two distinct channels, so the coordinator can cache
    a genuine "no data here" answer while never caching a failure:

    Returns:
      (value, reference_datetime) — the request SUCCEEDED and the body parsed:
      - value: float, or None when GeoMet answered but has no data for this
        point/time (e.g. a beyond-horizon timestep). None here is a valid,
        cacheable answer.
      - reference_datetime: model run time string or None.

    Raises (the request FAILED — the caller must NOT cache anything):
      RateLimitedError — HTTP 429 (rate limited); also drives the wave backoff.
      TransientGeoMetError — timeout, connection/DNS error, any other non-200,
        or an unparseable body.
    """
    time_str = timestep.strftime("%Y-%m-%dT%H:%M:%SZ")
    url = (
        f"{GEOMET_BASE_URL}"
        f"?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetFeatureInfo"
        f"&LAYERS={layer}&QUERY_LAYERS={layer}"
        f"&CRS={GEOMET_CRS}&BBOX={geomet_bbox}"
        f"&WIDTH=100&HEIGHT=100&I=50&J=50"
        f"&INFO_FORMAT=application/json&TIME={time_str}"
    )

    try:
        async with asyncio.timeout(timeout):
            async with session.get(url) as resp:
                resp.raise_for_status()
                # GeoMet returns Content-Type: text/html even for JSON
                data = await resp.json(content_type=None)
    except aiohttp.ClientResponseError as err:
        # Non-200 status (raised by raise_for_status). 429 gets its own type so
        # the wave can back off; both are failures and are never cached.
        _LOGGER.debug(
            "EC WEonG: HTTP %s querying %s at %s", err.status, layer, time_str,
        )
        if err.status == 429:
            raise RateLimitedError(
                f"Rate limited querying {layer} at {time_str}"
            ) from err
        raise TransientGeoMetError(
            f"HTTP {err.status} querying {layer} at {time_str}"
        ) from err
    except (asyncio.TimeoutError, aiohttp.ClientError, ValueError) as err:
        _LOGGER.debug(
            "EC WEonG: failed to query %s at %s: %s", layer, time_str, err,
        )
        raise TransientGeoMetError(
            f"Failed to query {layer} at {time_str}: {err}"
        ) from err

    return _parse_geomet_response(data)


# ---------------------------------------------------------------------------
# EC city feature parser (shared by config flow auto-detect and search)
# ---------------------------------------------------------------------------

def parse_ec_city_features(
    features: list[dict[str, Any]],
    language: str = "en",
) -> list[dict[str, Any]]:
    """Parse EC city features into a list of city dicts.

    Each returned dict has: id, name, province, lat, lon.
    Coordinates are extracted from the URL property (coords=lat,lon).
    """
    cities: list[dict[str, Any]] = []

    for feature in features:
        city_id = feature.get("id", "")
        props = feature.get("properties") or {}

        name = props.get("name")
        if isinstance(name, dict):
            name = name.get(language) or name.get("en") or ""
        if not name:
            name = city_id

        # Province from city code prefix (e.g. "qc-68" -> "QC")
        province = city_id.split("-")[0].upper() if "-" in city_id else ""

        # Extract coordinates from URL property (coords=lat,lon)
        lat = None
        lon = None
        url_str = (props.get("url") or {}).get("en", "")
        match = _COORDS_RE.search(url_str)
        if match:
            lat = float(match.group(1))
            lon = float(match.group(2))

        cities.append({
            "id": city_id,
            "name": name,
            "province": province,
            "lat": lat,
            "lon": lon,
        })

    return cities


# ---------------------------------------------------------------------------
# AQHI station discovery
# ---------------------------------------------------------------------------

async def discover_aqhi_station(
    session: aiohttp.ClientSession,
    lat: float,
    lon: float,
    api_base: str,
    timeout: int,
) -> str | None:
    """Find the nearest AQHI forecast station within +/-1.5 deg of the city.

    Returns the location_id string, or None if discovery fails.
    When multiple stations exist, picks the one closest to (lat, lon).
    """
    import math

    bbox = f"{lon - 1.5:.1f},{lat - 1.5:.1f},{lon + 1.5:.1f},{lat + 1.5:.1f}"
    url = (
        f"{api_base}/collections/aqhi-forecasts-realtime/items"
        f"?f=json&bbox={bbox}&limit=200&skipGeometry=true"
        f"&properties=location_id,location_name_en,location_latitude,location_longitude"
    )

    try:
        async with asyncio.timeout(timeout):
            async with session.get(url) as resp:
                resp.raise_for_status()
                data = await resp.json()
    except (asyncio.TimeoutError, aiohttp.ClientError, ValueError) as err:
        _LOGGER.debug("AQHI discovery failed: %s", err)
        return None

    features = data.get("features") or []
    if not features:
        return None

    # Deduplicate by location_id and collect coordinates for proximity sort
    stations: dict[str, dict] = {}
    for feature in features:
        props = feature.get("properties") or {}
        loc_id = props.get("location_id")
        if loc_id and loc_id not in stations:
            stations[loc_id] = {
                "location_id": loc_id,
                "name": props.get("location_name_en", loc_id),
                "lat": _safe_float(props.get("location_latitude")),
                "lon": _safe_float(props.get("location_longitude")),
            }

    if not stations:
        return None

    # Sort by proximity to the city; stations without coordinates go last
    cos_lat = math.cos(math.radians(lat))
    def _distance(station: dict) -> float:
        slat = station.get("lat")
        slon = station.get("lon")
        if slat is None or slon is None:
            return float("inf")
        dlat = slat - lat
        dlon = (slon - lon) * cos_lat
        return dlat ** 2 + dlon ** 2

    nearest = min(stations.values(), key=_distance)
    return nearest["location_id"]


# ---------------------------------------------------------------------------
# Yesterday's precipitation — climate-daily station discovery (issue #9)
# ---------------------------------------------------------------------------


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two lat/lon points."""
    import math

    radius_km = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    return radius_km * 2 * math.asin(math.sqrt(a))


def parse_precip_stations(data: dict, lat: float, lon: float) -> dict:
    """Find the nearest reporting and nearest split-capable climate stations.

    Pure function over a windowed ``climate-daily`` response. A station
    "reports precipitation" if any row has a non-null TOTAL_PRECIPITATION
    (0 counts — it's a measured dry day). A station is "split-capable" if any
    row has a non-null TOTAL_RAIN (combined-only stations always report null
    rain, even on dry days, so this reliably distinguishes them).

    Returns ``{"nearest": <station|None>, "nearest_split": <station|None>}``
    where each station is ``{station_id, name, type, distance_km, lat, lon}``.
    ``type`` is "split" or "combined". ``nearest_split`` may equal ``nearest``.
    """
    features = data.get("features") or []
    if not isinstance(features, list):
        features = []

    # Aggregate rows by station: a station reports if ANY row has non-null
    # total; it is split-capable if ANY row has non-null rain.
    stations: dict[str, dict] = {}
    for feature in features:
        props = feature.get("properties") or {}
        station_id = props.get("CLIMATE_IDENTIFIER")
        if not station_id:
            continue

        total = _safe_float(props.get("TOTAL_PRECIPITATION"))
        rain = _safe_float(props.get("TOTAL_RAIN"))

        geom = feature.get("geometry") or {}
        coords = geom.get("coordinates") or []
        slat = _safe_float(coords[1]) if len(coords) >= 2 else None
        slon = _safe_float(coords[0]) if len(coords) >= 2 else None

        entry = stations.get(station_id)
        if entry is None:
            entry = {
                "station_id": station_id,
                "name": props.get("STATION_NAME") or station_id,
                "lat": slat,
                "lon": slon,
                "reports": False,
                "split": False,
            }
            stations[station_id] = entry

        # Backfill coordinates if an earlier row lacked them
        if entry["lat"] is None and slat is not None:
            entry["lat"] = slat
            entry["lon"] = slon

        if total is not None:
            entry["reports"] = True
        if rain is not None:
            entry["split"] = True

    def _finalize(entry: dict) -> dict:
        slat = entry["lat"]
        slon = entry["lon"]
        distance_km = (
            _haversine_km(lat, lon, slat, slon)
            if slat is not None and slon is not None
            else float("inf")
        )
        return {
            "station_id": entry["station_id"],
            "name": entry["name"],
            "type": "split" if entry["split"] else "combined",
            "distance_km": round(distance_km, 1),
            "lat": slat,
            "lon": slon,
        }

    reporting = [_finalize(e) for e in stations.values() if e["reports"]]
    if not reporting:
        return {"nearest": None, "nearest_split": None}

    reporting.sort(key=lambda s: s["distance_km"])
    nearest = reporting[0]

    split_stations = [s for s in reporting if s["type"] == "split"]
    nearest_split = split_stations[0] if split_stations else None

    return {"nearest": nearest, "nearest_split": nearest_split}


async def discover_precip_stations(
    session: aiohttp.ClientSession,
    lat: float,
    lon: float,
    api_base: str,
    timeout: int,
    window_dates: tuple[str, str] | None = None,
    radius_deg: float = 1.0,
) -> dict:
    """Query climate-daily over a recent window and discover precip stations.

    ``window_dates`` is an explicit (start_iso, end_iso) range; when omitted,
    the caller-side default is the last 8 days. Returns the same shape as
    ``parse_precip_stations``; ``{"nearest": None, "nearest_split": None}`` on
    any network error.
    """
    from datetime import date, timedelta

    if window_dates is None:
        end = date.today() - timedelta(days=1)
        start = end - timedelta(days=7)
        window_dates = (start.isoformat(), end.isoformat())

    bbox = (
        f"{lon - radius_deg:.1f},{lat - radius_deg:.1f},"
        f"{lon + radius_deg:.1f},{lat + radius_deg:.1f}"
    )
    url = (
        f"{api_base}/collections/climate-daily/items"
        f"?f=json&bbox={bbox}&datetime={window_dates[0]}/{window_dates[1]}"
        f"&limit=1000"
        f"&properties=CLIMATE_IDENTIFIER,STATION_NAME,"
        f"TOTAL_PRECIPITATION,TOTAL_RAIN,TOTAL_SNOW"
    )

    try:
        async with asyncio.timeout(timeout):
            async with session.get(url) as resp:
                resp.raise_for_status()
                data = await resp.json()
    except (asyncio.TimeoutError, aiohttp.ClientError, ValueError) as err:
        _LOGGER.debug("Precip station discovery failed: %s", err)
        return {"nearest": None, "nearest_split": None}

    return parse_precip_stations(data, lat, lon)

