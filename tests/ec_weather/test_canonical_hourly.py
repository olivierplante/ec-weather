"""Canonical per-timestamp hourly record — one source decision per field.

The user directive: the backend decides ONCE which datasource feeds each hour,
never the frontend, and the hourly strip (``build_unified_hourly``) and the daily
popup timesteps (``enrich_timesteps``) must be views over ONE canonical
per-timestamp record. ``canonical_hourly_record`` is that single place. These
tests pin the invariant with teeth:

- for ANY timestamp present in BOTH surfaces' outputs, the FULL records are
  identical field-by-field (not just POP — the whole record);
- EC-covered hours keep their EC temp / icon / wind exactly;
- ``HOURLY_SOURCE_MAP`` cannot drift from the record shape.
"""

from __future__ import annotations

import itertools

from ec_weather.transforms import (
    HOURLY_SOURCE_MAP,
    build_unified_hourly,
    canonical_hourly_record,
    enrich_timesteps,
)


TS = "2026-03-23T14:00:00Z"


def _ec_item(dt: str, **overrides) -> dict:
    """EC citypage hourly item (parse_hourly shape)."""
    base = {
        "time": dt,
        "temp": -4.7,
        "feels_like": -10.0,
        "condition": "Cloudy",
        "icon_code": 3,
        "precipitation_probability": 20,
        "wind_speed": 18,
        "wind_gust": 33,
        "wind_direction": "NW",
    }
    base.update(overrides)
    return base


def _weong_hourly(**overrides) -> dict:
    """WEonG hourly dict (project_hourly / to_hourly_dict shape)."""
    base = {
        "rain_mm": 1.5,
        "snow_cm": None,
        "sky_state": 9,
        "temp": -5.0,
        "precipitation_probability": 60,
        "freezing_precip_mm": None,
        "ice_pellet_cm": None,
    }
    base.update(overrides)
    return base


def _weong_timestep(dt: str, **overrides) -> dict:
    """WEonG timestep (project_periods / to_dict shape)."""
    base = {
        "time": dt,
        "temp": -5.0,
        "feels_like": None,
        "icon_code": None,
        "condition": None,
        "precipitation_probability": 60,
        "rain_mm": 1.5,
        "snow_cm": None,
        "freezing_precip_mm": None,
        "ice_pellet_cm": None,
        "wind_speed": None,
        "wind_gust": None,
        "wind_direction": None,
        "sky_state": 9,
    }
    base.update(overrides)
    return base


def _strip_record(ec: dict | None, weong: dict | None) -> dict:
    ec_hourly = [ec] if ec else []
    weong_hourly = {TS: weong} if weong else {}
    return build_unified_hourly(ec_hourly, weong_hourly)[0]


def _popup_record(ec: dict | None, weong_ts: dict) -> dict:
    hourly_lookup = {TS: ec} if ec else {}
    return enrich_timesteps({"timesteps": [weong_ts]}, hourly_lookup)[0]


# ---------------------------------------------------------------------------
# SOURCE_MAP with teeth — documentation cannot drift from the record
# ---------------------------------------------------------------------------

class TestSourceMapTeeth:
    def test_map_keys_match_record_fields(self):
        """HOURLY_SOURCE_MAP must document EXACTLY the record's fields."""
        record = canonical_hourly_record(
            TS, _ec_item(TS), _weong_hourly(),
        )
        assert set(HOURLY_SOURCE_MAP) == set(record)

    def test_every_entry_documents_source_and_fallback(self):
        for field, spec in HOURLY_SOURCE_MAP.items():
            assert spec.get("source"), f"{field} missing source"
            assert "fallback" in spec, f"{field} missing fallback key"


# ---------------------------------------------------------------------------
# EC-covered hours keep EC temp / icon / wind exactly (regression)
# ---------------------------------------------------------------------------

class TestECCoveredRegression:
    def test_ec_temp_icon_wind_preserved(self):
        record = canonical_hourly_record(TS, _ec_item(TS), _weong_hourly())
        assert record["temp"] == -4.7          # EC temp wins over WEonG -5.0
        assert record["icon_code"] == 3         # EC icon wins over sky_state derive
        assert record["condition"] == "Cloudy"
        assert record["feels_like"] == -10.0
        assert record["wind_speed"] == 18
        assert record["wind_gust"] == 33
        assert record["wind_direction"] == "NW"
        # WEonG owns amounts + POP
        assert record["rain_mm"] == 1.5
        assert record["precipitation_probability"] == 60

    def test_beyond_ec_uses_weong_temp_and_derived_icon(self):
        record = canonical_hourly_record(
            TS, None, _weong_hourly(sky_state=2, rain_mm=None),
        )
        assert record["temp"] == -5.0           # WEonG AirTemp
        assert record["feels_like"] is None     # EC-only field
        assert record["wind_speed"] is None
        # sky_state=2 at hour 14 (daytime) → Sunny(0)
        assert record["icon_code"] == 0
        assert record["condition"] == "Sunny"


# ---------------------------------------------------------------------------
# Property: strip record == popup record, FULL field-by-field, across states
# ---------------------------------------------------------------------------

class TestSurfacesProduceIdenticalRecords:
    def test_full_record_matches_across_source_matrix(self):
        temps = [None, -4.7, 0.0]
        pops = [None, 0, 60]
        rains = [None, 1.5]
        skies = [None, 2, 9]
        icons = [None, 3]
        for ec_temp, ec_icon, weong_pop, rain, sky in itertools.product(
            temps, icons, pops, rains, skies,
        ):
            # EC present branch
            ec = _ec_item(
                TS, temp=ec_temp, icon_code=ec_icon,
                condition="Cloudy" if ec_icon is not None else None,
                precipitation_probability=None,
            )
            weong_h = _weong_hourly(
                temp=-5.0, precipitation_probability=weong_pop,
                rain_mm=rain, sky_state=sky,
            )
            weong_ts = _weong_timestep(
                TS, temp=-5.0, precipitation_probability=weong_pop,
                rain_mm=rain, sky_state=sky,
            )
            strip = _strip_record(ec, weong_h)
            popup = _popup_record(ec, weong_ts)
            assert strip == popup, (
                f"strip != popup at ec_temp={ec_temp} ec_icon={ec_icon} "
                f"pop={weong_pop} rain={rain} sky={sky}:\n{strip}\n{popup}"
            )

    def test_full_record_matches_weong_only(self):
        """Beyond EC coverage: both surfaces derive the identical record."""
        for sky, rain in itertools.product([None, 2, 9], [None, 1.5]):
            weong_h = _weong_hourly(sky_state=sky, rain_mm=rain)
            weong_ts = _weong_timestep(TS, sky_state=sky, rain_mm=rain)
            strip = _strip_record(None, weong_h)
            popup = _popup_record(None, weong_ts)
            assert strip == popup, f"sky={sky} rain={rain}:\n{strip}\n{popup}"


# ---------------------------------------------------------------------------
# Temp representation: one rounded (1-decimal) value on every surface
# ---------------------------------------------------------------------------

class TestTempRepresentation:
    def test_temp_rounded_to_one_decimal(self):
        record = canonical_hourly_record(
            TS, _ec_item(TS, temp=-4.73), _weong_hourly(),
        )
        assert record["temp"] == -4.7

    def test_strip_and_popup_carry_same_rounded_temp(self):
        ec = _ec_item(TS, temp=-4.73)
        strip = _strip_record(ec, _weong_hourly())
        popup = _popup_record(ec, _weong_timestep(TS))
        assert strip["temp"] == popup["temp"] == -4.7
