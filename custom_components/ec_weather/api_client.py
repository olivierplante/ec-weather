"""HTTP/API client helpers for the EC Weather integration.

This module contains all outbound HTTP concerns:
- fetch_json_with_retry: generic JSON fetch with retry for transient errors
- query_geomet_feature_info: GeoMet WMS GetFeatureInfo point query
- parse_ec_city_features: parse EC city features from API response
- missing_data_points: detect current-conditions fields a citypage never reports
- find_nearest_complete_city: find the nearest citypage that reports everything
- discover_aqhi_station: find nearest AQHI station via EC API

No Home Assistant dependencies — accepts aiohttp sessions as parameters.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timezone
from typing import Any

import aiohttp

from .utils import safe_float as _safe_float

from .const import (
    FETCH_RETRIES,
    FETCH_RETRY_DELAY,
    GEOMET_BASE_URL,
    GEOMET_CRS,
    PRECIP_STATION_FRESHNESS_DAYS,
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


class AqhiDiscoveryError(Exception):
    """Raised when discover_aqhi_station's HTTP request fails.

    Mirrors the failure-vs-no-data split used by query_geomet_feature_info:
    a network error/timeout/bad JSON is not the same fact as EC answering
    "no station found" (a plain ``None`` return). The AQHI coordinator's
    self-heal rate-limits itself to one rediscovery attempt per 24h; without
    this distinction a boot-time network blip would burn that window and
    strand a healthy station without self-heal until the next restart. Call
    sites that don't care about the distinction (config flow, repairs) catch
    this and treat it exactly like a "not found" result.
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
# Current-conditions completeness probe
#
# Some EC citypages are backed by automatic observation stations that
# structurally never publish certain current-conditions fields (e.g. an
# automatic station never has a human-observed sky condition). This is used
# during onboarding to warn the user and offer the nearest citypage that
# reports everything.
# ---------------------------------------------------------------------------

def missing_data_points(props: dict) -> list[str]:
    """Return the current-conditions data points a citypage never reports.

    Checks nested presence for a fixed set of data points — a missing key at
    any level, or a None leaf, means missing. Returns the missing keys in a
    stable order; an empty list means the citypage is fully reporting.

    Deliberately NOT probed here (their absence is weather-dependent, not a
    station trait, so probing them would misclassify a normal reporting
    station as incomplete):
    - wind gust: EC omits it below a wind-gust threshold
    - wind direction: absent when winds are calm
    """
    current = props.get("currentConditions") or {}

    missing: list[str] = []

    # sky_condition is present if EITHER the condition text or the icon code
    # value exists; it's missing only when both are absent/null.
    condition_text = (current.get("condition") or {}).get("en")
    icon_code_value = (current.get("iconCode") or {}).get("value")
    if condition_text is None and icon_code_value is None:
        missing.append("sky_condition")

    temperature_value = (current.get("temperature") or {}).get("value") or {}
    if temperature_value.get("en") is None:
        missing.append("temperature")

    humidity_value = (current.get("relativeHumidity") or {}).get("value") or {}
    if humidity_value.get("en") is None:
        missing.append("humidity")

    # Wind speed can legitimately be the string "calm" — any non-null value
    # (including "calm") counts as present.
    wind_speed_value = ((current.get("wind") or {}).get("speed") or {}).get(
        "value"
    ) or {}
    if wind_speed_value.get("en") is None:
        missing.append("wind_speed")

    return missing


# ---------------------------------------------------------------------------
# EC city feature parser (shared by config flow auto-detect and search)
# ---------------------------------------------------------------------------

def parse_ec_city_features(
    features: list[dict[str, Any]],
    language: str = "en",
) -> list[dict[str, Any]]:
    """Parse EC city features into a list of city dicts.

    Each returned dict has: id, name, province, lat, lon, missing.
    Coordinates are extracted from the URL property (coords=lat,lon).
    ``missing`` is the output of ``missing_data_points`` — the search
    response already contains full currentConditions, so this costs no
    extra API calls.
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
            "missing": missing_data_points(props),
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

    When multiple stations exist, picks the one closest to (lat, lon).

    EC changed the aqhi-forecasts-realtime collection (Sept 2026): the item
    properties location_latitude/location_longitude no longer exist (a 400
    InvalidParameterValue if requested), so station coordinates now come only
    from each feature's GeoJSON geometry ({"type": "Point", "coordinates":
    [lon, lat]}). The collection's datetime= query parameter also stopped
    matching rows by forecast_datetime — it appears publication-based and
    returns zero rows even for a healthy station — so the freshness filter
    that used to run server-side now runs client-side: a station qualifies
    only if at least one of its rows has forecast_datetime >= the current UTC
    hour, so a station lingering in the collection with only past forecast
    items (e.g. a retired station whose last publication hasn't rolled off
    yet) can never be selected as its own replacement.

    Returns:
      The location_id string, or None when the request SUCCEEDED but EC
      genuinely has no qualifying station nearby (a cacheable, meaningful
      answer).

    Raises:
      AqhiDiscoveryError — the request itself FAILED (network error, timeout,
      or an unparseable body). This is deliberately not the same as None; see
      AqhiDiscoveryError's docstring for why callers must tell them apart.
    """
    import math

    now_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    bbox = f"{lon - 1.5:.1f},{lat - 1.5:.1f},{lon + 1.5:.1f},{lat + 1.5:.1f}"
    url = (
        f"{api_base}/collections/aqhi-forecasts-realtime/items"
        f"?f=json&bbox={bbox}&limit=200&sortby=-forecast_datetime"
        f"&properties=location_id,location_name_en,forecast_datetime"
    )

    try:
        async with asyncio.timeout(timeout):
            async with session.get(url) as resp:
                resp.raise_for_status()
                data = await resp.json()
    except (asyncio.TimeoutError, aiohttp.ClientError, ValueError) as err:
        _LOGGER.debug("AQHI discovery failed: %s", err)
        raise AqhiDiscoveryError(f"AQHI discovery failed: {err}") from err

    features = data.get("features") or []
    if not features:
        return None

    # Deduplicate by location_id, taking coordinates from geometry (the only
    # place they're still published). A station qualifies only once ANY of
    # its rows clears the current-hour freshness check — a single stale row
    # from an otherwise-healthy station must not disqualify it, and a single
    # fresh row is enough to rescue a station from being treated as dead.
    stations: dict[str, dict] = {}
    for feature in features:
        props = feature.get("properties") or {}
        loc_id = props.get("location_id")
        if not loc_id:
            continue

        fdt_str = props.get("forecast_datetime", "")
        try:
            fdt = datetime.fromisoformat(fdt_str.replace("Z", "+00:00"))
            is_fresh = fdt >= now_hour
        except (ValueError, AttributeError):
            is_fresh = False

        entry = stations.get(loc_id)
        if entry is None:
            geometry = feature.get("geometry") or {}
            coordinates = geometry.get("coordinates") or []
            entry = {
                "location_id": loc_id,
                "name": props.get("location_name_en", loc_id),
                "lat": _safe_float(coordinates[1]) if len(coordinates) >= 2 else None,
                "lon": _safe_float(coordinates[0]) if len(coordinates) >= 2 else None,
                "fresh": False,
            }
            stations[loc_id] = entry
        if is_fresh:
            entry["fresh"] = True

    qualifying = {loc_id: s for loc_id, s in stations.items() if s["fresh"]}
    if not qualifying:
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

    nearest = min(qualifying.values(), key=_distance)
    return nearest["location_id"]


# ---------------------------------------------------------------------------
# Nearest fully-reporting citypage (onboarding station-choice step)
# ---------------------------------------------------------------------------

async def find_nearest_complete_city(
    session: aiohttp.ClientSession,
    lat: float,
    lon: float,
    exclude_id: str,
    api_base: str,
    timeout: int,
) -> dict | None:
    """Find the nearest citypage that reports every current-conditions field.

    Expands the search bbox in rings (half-widths 1.0, 2.0, then 4.0 degrees
    around (lat, lon)) and stops at the first ring containing a qualifying
    candidate — a citypage with an empty ``missing_data_points`` result whose
    id isn't ``exclude_id`` (the citypage the user already picked). Returns
    None if no such citypage exists within the 4.0 degree ring.

    The properties filter below requests only the fields missing_data_points
    needs, keeping payloads ~75x smaller than a full citypage response. With
    this filter the API omits a requested property entirely when it is null,
    so missing_data_points works unchanged on the reduced documents.

    Returns the closest qualifying candidate as
    ``{"id", "name", "lat", "lon", "distance_km"}`` (distance rounded to the
    nearest whole km), or None on a network error or no match (logged at
    debug level, mirroring discover_aqhi_station).
    """
    for half_width in (1.0, 2.0, 4.0):
        bbox = (
            f"{lon - half_width:.1f},{lat - half_width:.1f},"
            f"{lon + half_width:.1f},{lat + half_width:.1f}"
        )
        url = (
            f"{api_base}/collections/citypageweather-realtime/items"
            f"?f=json&bbox={bbox}&skipGeometry=true&limit=200"
            f"&properties=name.en,name.fr,url.en,"
            f"currentConditions.condition.en,currentConditions.iconCode.value,"
            f"currentConditions.temperature.value.en,"
            f"currentConditions.relativeHumidity.value.en,"
            f"currentConditions.wind.speed.value.en"
        )

        try:
            async with asyncio.timeout(timeout):
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
        except (asyncio.TimeoutError, aiohttp.ClientError, ValueError) as err:
            _LOGGER.debug("Nearest complete citypage discovery failed: %s", err)
            return None

        features = data.get("features") or []
        candidates: list[dict] = []
        for feature in features:
            city_id = feature.get("id", "")
            if city_id == exclude_id:
                continue

            props = feature.get("properties") or {}
            if missing_data_points(props):
                continue

            url_str = (props.get("url") or {}).get("en", "")
            match = _COORDS_RE.search(url_str)
            if not match:
                continue
            candidate_lat = float(match.group(1))
            candidate_lon = float(match.group(2))

            candidates.append({
                "id": city_id,
                "name": props.get("name") or city_id,
                "lat": candidate_lat,
                "lon": candidate_lon,
                "distance_km": _haversine_km(
                    lat, lon, candidate_lat, candidate_lon
                ),
            })

        if candidates:
            nearest = min(candidates, key=lambda c: c["distance_km"])
            nearest["distance_km"] = round(nearest["distance_km"])
            return nearest

    return None


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


def parse_precip_stations(
    data: dict, lat: float, lon: float, window_end: str | None = None
) -> dict:
    """Find the nearest reporting and nearest split-capable climate stations.

    Pure function over a windowed ``climate-daily`` response. A station
    "reports precipitation" if any row has a non-null TOTAL_PRECIPITATION
    (0 counts — it's a measured dry day). A station is "split-capable" if any
    row has a non-null TOTAL_RAIN (combined-only stations always report null
    rain, even on dry days, so this reliably distinguishes them).

    ``window_end`` is the ISO end date of the requested window. When given,
    each candidate's most recent non-null date is checked against it: a
    station is "fresh" when that date is within ``PRECIP_STATION_FRESHNESS_
    DAYS`` of ``window_end``. Selection prefers the nearest FRESH station;
    when NO reporting station is fresh anywhere (EC-wide publication
    backlogs are common), selection falls back to the old nearest-reporting
    behavior. Split-capable freshness is judged on the station's latest
    non-null TOTAL_RAIN date (rain/snow breakdowns can lag the total
    independently), not its TOTAL_PRECIPITATION date. ``window_end=None``
    (the default) skips freshness entirely — legacy nearest-reporting-wins
    behavior, for callers that don't have a window to compare against.

    Returns ``{"nearest": <station|None>, "nearest_split": <station|None>}``
    where each station is ``{station_id, name, type, distance_km, lat, lon,
    latest_precip_date}``. ``type`` is "split" or "combined".
    ``latest_precip_date`` is the ISO date of the station's most recent
    non-null TOTAL_PRECIPITATION row, or None when no LOCAL_DATE could be
    determined. ``nearest_split`` may equal ``nearest``.
    """
    features = data.get("features") or []
    if not isinstance(features, list):
        features = []

    # Aggregate rows by station: a station reports if ANY row has non-null
    # total; it is split-capable if ANY row has non-null rain. Track the
    # latest date backing each of those two facts separately (see docstring).
    stations: dict[str, dict] = {}
    for feature in features:
        props = feature.get("properties") or {}
        station_id = props.get("CLIMATE_IDENTIFIER")
        if not station_id:
            continue

        total = _safe_float(props.get("TOTAL_PRECIPITATION"))
        rain = _safe_float(props.get("TOTAL_RAIN"))
        local_date = props.get("LOCAL_DATE")
        # LOCAL_DATE can carry a full timestamp — keep only the date part so
        # it compares cleanly against the ISO-date window_end.
        row_date = local_date[:10] if isinstance(local_date, str) else None

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
                "latest_precip_date": None,
                "latest_rain_date": None,
            }
            stations[station_id] = entry

        # Backfill coordinates if an earlier row lacked them
        if entry["lat"] is None and slat is not None:
            entry["lat"] = slat
            entry["lon"] = slon

        if total is not None:
            entry["reports"] = True
            if row_date and (
                entry["latest_precip_date"] is None
                or row_date > entry["latest_precip_date"]
            ):
                entry["latest_precip_date"] = row_date
        if rain is not None:
            entry["split"] = True
            if row_date and (
                entry["latest_rain_date"] is None
                or row_date > entry["latest_rain_date"]
            ):
                entry["latest_rain_date"] = row_date

    def _is_fresh(date_str: str | None) -> bool:
        if window_end is None or date_str is None:
            return False
        try:
            end = date.fromisoformat(window_end)
            latest = date.fromisoformat(date_str)
        except ValueError:
            return False
        return (end - latest).days <= PRECIP_STATION_FRESHNESS_DAYS

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
            "latest_precip_date": entry["latest_precip_date"],
        }

    reporting = [_finalize(e) for e in stations.values() if e["reports"]]
    if not reporting:
        return {"nearest": None, "nearest_split": None}

    reporting.sort(key=lambda s: s["distance_km"])

    fresh_reporting = [s for s in reporting if _is_fresh(s["latest_precip_date"])]
    nearest = fresh_reporting[0] if fresh_reporting else reporting[0]

    split_stations = [s for s in reporting if s["type"] == "split"]
    fresh_split_ids = {
        station_id
        for station_id, entry in stations.items()
        if entry["split"] and _is_fresh(entry["latest_rain_date"])
    }
    fresh_split_stations = [
        s for s in split_stations if s["station_id"] in fresh_split_ids
    ]
    if fresh_split_stations:
        nearest_split = fresh_split_stations[0]
    elif split_stations:
        nearest_split = split_stations[0]
    else:
        nearest_split = None

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
    any network error. LOCAL_DATE is requested and the window's end date is
    passed through to ``parse_precip_stations`` so it can prefer a FRESH
    station over a merely-reporting-but-stale one.
    """
    from datetime import timedelta

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
        f"&properties=CLIMATE_IDENTIFIER,STATION_NAME,LOCAL_DATE,"
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

    return parse_precip_stations(data, lat, lon, window_end=window_dates[1])

