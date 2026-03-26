"""Phase A tests — card renders from EC data alone, WEonG enriches in background.

Tests verify:
1. Daily sensor output is consistent shape with or without WEonG data
2. EC precip_accum fields pass through to daily output when WEonG absent
3. merge_weong_into_daily produces uniform output shape with empty WEonG
4. Daily columns have all fields needed for card rendering without WEonG
"""

from __future__ import annotations

from freezegun import freeze_time

from ec_weather.transforms import merge_weong_into_daily


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _daily_item(
    period: str,
    date: str,
    temp_high: float | None = 2,
    temp_low: float | None = -8,
    **overrides,
) -> dict:
    """Build a daily forecast item matching parse_daily output."""
    base = {
        "period": period,
        "date": date,
        "temp_high": temp_high,
        "temp_low": temp_low,
        "icon_code": 2,
        "icon_code_night": 33,
        "condition": "Partly cloudy",
        "condition_night": "Clear",
        "text_summary": "Partly cloudy. High 2.",
        "text_summary_night": "Clear. Low minus 8.",
        "feels_like_high": -2,
        "feels_like_low": -12,
        "wind_speed": 15,
        "wind_gust": 25,
        "wind_direction": "NW",
        "wind_speed_night": 10,
        "wind_gust_night": None,
        "wind_direction_night": "W",
        "humidity": 45,
        "humidity_night": 80,
        "uv_index": 3,
        "uv_category": "moderate",
        "precip_accum_amount": None,
        "precip_accum_unit": None,
        "precip_accum_name": None,
        "precip_accum_amount_night": None,
        "precip_accum_unit_night": None,
        "precip_accum_name_night": None,
        "precip_type": None,
    }
    base.update(overrides)
    return base


def _weong_period(pop=65, rain=3.2, snow=None, timesteps=None):
    """Build a minimal WEonG period."""
    return {
        "pop": pop,
        "rain_mm": rain,
        "snow_cm": snow,
        "timesteps": timesteps or [],
    }


# ---------------------------------------------------------------------------
# Daily output shape consistency — EC only vs EC + WEonG
# ---------------------------------------------------------------------------

class TestDailyOutputShapeWithoutWEonG:
    """Verify daily output has a consistent shape when WEonG is absent."""

    def test_empty_weong_produces_null_precip_fields(self):
        """Empty weong_periods → all WEonG-specific fields present but null."""
        daily = [_daily_item("Monday", "2026-03-23")]
        result = merge_weong_into_daily(daily, {})

        item = result[0]
        assert item["precip_prob_day"] is None
        assert item["precip_prob_night"] is None
        assert item["precip_prob"] is None
        assert item["rain_mm_day"] is None
        assert item["snow_cm_day"] is None
        assert item["rain_mm_night"] is None
        assert item["snow_cm_night"] is None

    def test_empty_weong_produces_empty_timesteps(self):
        """Empty weong_periods → timesteps_day/night are empty lists."""
        daily = [_daily_item("Monday", "2026-03-23")]
        result = merge_weong_into_daily(daily, {})

        item = result[0]
        assert item["timesteps_day"] == []
        assert item["timesteps_night"] == []

    def test_empty_weong_icons_complete_true(self):
        """Empty weong_periods + no timesteps → icons_complete is True."""
        daily = [_daily_item("Monday", "2026-03-23")]
        result = merge_weong_into_daily(daily, {})

        assert result[0]["icons_complete"] is True

    def test_ec_fields_preserved_without_weong(self):
        """EC daily fields pass through untouched when WEonG is absent."""
        daily = [_daily_item("Monday", "2026-03-23",
                             precip_accum_amount=5.0,
                             precip_accum_unit="cm",
                             precip_accum_name="snow")]
        result = merge_weong_into_daily(daily, {})

        item = result[0]
        # EC fields preserved
        assert item["icon_code"] == 2
        assert item["icon_code_night"] == 33
        assert item["temp_high"] == 2
        assert item["temp_low"] == -8
        assert item["precip_accum_amount"] == 5.0
        assert item["precip_accum_unit"] == "cm"
        assert item["precip_accum_name"] == "snow"

    def test_multiple_days_without_weong(self):
        """Multiple daily items all get consistent WEonG null fields."""
        daily = [
            _daily_item("Monday", "2026-03-23"),
            _daily_item("Tuesday", "2026-03-24"),
            _daily_item("Wednesday", "2026-03-25"),
        ]
        result = merge_weong_into_daily(daily, {})

        assert len(result) == 3
        for item in result:
            assert "precip_prob" in item
            assert "timesteps_day" in item
            assert "timesteps_night" in item
            assert "icons_complete" in item


# ---------------------------------------------------------------------------
# EC precip_accum availability for daily columns
# ---------------------------------------------------------------------------

class TestECPrecipAccumInDailyColumns:
    """Verify EC precip_accum fields are available for daily column rendering."""

    def test_day_snow_accumulation_passed_through(self):
        """EC precip_accum with snow → available in daily output."""
        daily = [_daily_item("Monday", "2026-03-23",
                             precip_accum_amount=5.0,
                             precip_accum_unit="cm",
                             precip_accum_name="snow")]
        result = merge_weong_into_daily(daily, {})

        item = result[0]
        assert item["precip_accum_amount"] == 5.0
        assert item["precip_accum_unit"] == "cm"
        assert item["precip_accum_name"] == "snow"

    def test_night_rain_accumulation_passed_through(self):
        """EC night precip_accum with rain → available in daily output."""
        daily = [_daily_item("Monday", "2026-03-23",
                             precip_accum_amount_night=12.0,
                             precip_accum_unit_night="mm",
                             precip_accum_name_night="rain")]
        result = merge_weong_into_daily(daily, {})

        item = result[0]
        assert item["precip_accum_amount_night"] == 12.0
        assert item["precip_accum_unit_night"] == "mm"
        assert item["precip_accum_name_night"] == "rain"

    def test_ec_accum_coexists_with_weong_amounts(self):
        """When both EC accum and WEonG amounts present, both available."""
        daily = [_daily_item("Monday", "2026-03-23",
                             precip_accum_amount=5.0,
                             precip_accum_unit="cm",
                             precip_accum_name="snow")]
        weong_periods = {
            ("2026-03-23", "day"): _weong_period(pop=70, rain=0, snow=4.5),
            ("2026-03-23", "night"): _weong_period(pop=40),
        }
        result = merge_weong_into_daily(daily, weong_periods)

        item = result[0]
        # EC accum preserved
        assert item["precip_accum_amount"] == 5.0
        # WEonG amounts also present
        assert item["snow_cm_day"] == 4.5

    def test_night_only_period_accum_preserved(self):
        """Night-only period (Tonight) EC accum preserved without WEonG."""
        daily = [_daily_item("Tonight", "2026-03-22",
                             temp_high=None, temp_low=-8,
                             icon_code=None, icon_code_night=33,
                             precip_accum_amount_night=2.0,
                             precip_accum_unit_night="cm",
                             precip_accum_name_night="snow")]
        result = merge_weong_into_daily(daily, {})

        item = result[0]
        assert item["precip_accum_amount_night"] == 2.0
        assert item["precip_accum_unit_night"] == "cm"


# ---------------------------------------------------------------------------
# WEonG enrichment arrives later — consistent shape transitions
# ---------------------------------------------------------------------------

class TestWEonGEnrichmentTransition:
    """Verify output transitions cleanly from EC-only to EC+WEonG."""

    def test_weong_arrival_adds_pop_without_breaking_shape(self):
        """When WEonG data arrives, POP fields get real values; other fields unchanged."""
        daily = [_daily_item("Monday", "2026-03-23",
                             precip_accum_amount=5.0,
                             precip_accum_unit="cm",
                             precip_accum_name="snow")]

        # First render: no WEonG
        result_before = merge_weong_into_daily(daily, {})
        assert result_before[0]["precip_prob"] is None
        assert result_before[0]["precip_accum_amount"] == 5.0

        # Second render: WEonG arrives
        weong_periods = {
            ("2026-03-23", "day"): _weong_period(pop=70, snow=4.5),
            ("2026-03-23", "night"): _weong_period(pop=40, snow=1.0),
        }
        result_after = merge_weong_into_daily(daily, weong_periods)
        assert result_after[0]["precip_prob"] == 70
        # EC accum still present
        assert result_after[0]["precip_accum_amount"] == 5.0
        # WEonG amounts now available
        assert result_after[0]["snow_cm_day"] == 4.5

    def test_output_keys_same_with_and_without_weong(self):
        """The set of keys in daily output is the same regardless of WEonG presence."""
        daily = [_daily_item("Monday", "2026-03-23")]

        result_no_weong = merge_weong_into_daily(daily, {})
        weong_periods = {
            ("2026-03-23", "day"): _weong_period(pop=50),
            ("2026-03-23", "night"): _weong_period(pop=30),
        }
        result_with_weong = merge_weong_into_daily(daily, weong_periods)

        keys_no_weong = set(result_no_weong[0].keys())
        keys_with_weong = set(result_with_weong[0].keys())
        assert keys_no_weong == keys_with_weong


# ---------------------------------------------------------------------------
# Daily sensor always produces uniform shape
# ---------------------------------------------------------------------------

class TestDailySensorUniformOutput:
    """The daily sensor must always call merge_weong_into_daily for consistent shape.

    Currently sensor.py short-circuits when weong_periods is empty, returning
    raw daily items that lack WEonG-specific fields. Phase A fixes this by
    always merging (even with empty WEonG), ensuring the card gets a uniform
    shape regardless of WEonG availability.
    """

    def test_sensor_output_has_weong_fields_even_without_weong(self):
        """Daily sensor output must include precip_prob, timesteps, icons_complete
        even when WEonG coordinator has no data."""
        # Simulate sensor behavior: always merge, even with empty WEonG
        daily = [_daily_item("Monday", "2026-03-23")]
        result = merge_weong_into_daily(daily, {})

        item = result[0]
        # These fields must always exist for card rendering
        required_fields = [
            "precip_prob", "precip_prob_day", "precip_prob_night",
            "rain_mm_day", "snow_cm_day", "rain_mm_night", "snow_cm_night",
            "timesteps_day", "timesteps_night", "icons_complete",
        ]
        for field in required_fields:
            assert field in item, f"Missing required field: {field}"
