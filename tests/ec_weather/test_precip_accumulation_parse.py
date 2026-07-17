"""Tests for _parse_precip_accumulation — EC precipitation accumulation shape.

Covers the observed live bug: a forecast period with no accumulation object
published ``"precip_accum_unit": {}`` into the sensor attributes instead of
None. Absent or unparseable amounts must resolve cleanly to None on all three
fields; the present shape must still parse.
"""

from __future__ import annotations

from ec_weather.parsing import _parse_precip_accumulation


class TestParsePrecipAccumulation:
    def test_present_shape_parses(self):
        """A stated rain accumulation resolves amount/unit/name."""
        period = {
            "precipitation": {
                "accumulation": {
                    "name": {"en": "rain"},
                    "amount": {
                        "value": {"en": 5},
                        "units": {"en": "mm"},
                    },
                }
            }
        }
        result = _parse_precip_accumulation(period, "en")
        assert result["precip_accum_amount"] == 5.0
        assert result["precip_accum_unit"] == "mm"
        assert result["precip_accum_name"] == "rain"

    def test_present_snow_cm_shape_parses(self):
        """A stated snow accumulation resolves cm unit."""
        period = {
            "precipitation": {
                "accumulation": {
                    "name": {"en": "snow"},
                    "amount": {
                        "value": {"en": 4},
                        "units": {"en": "cm"},
                    },
                }
            }
        }
        result = _parse_precip_accumulation(period, "en")
        assert result["precip_accum_amount"] == 4.0
        assert result["precip_accum_unit"] == "cm"
        assert result["precip_accum_name"] == "snow"

    def test_absent_amount_object_all_none(self):
        """No amount object → all three fields None, never an empty dict."""
        period = {"precipitation": {"accumulation": {}}}
        result = _parse_precip_accumulation(period, "en")
        assert result["precip_accum_amount"] is None
        assert result["precip_accum_unit"] is None
        assert result["precip_accum_name"] is None

    def test_empty_amount_object_all_none(self):
        """An explicitly empty amount object resolves to None on all fields."""
        period = {"precipitation": {"accumulation": {"amount": {}}}}
        result = _parse_precip_accumulation(period, "en")
        assert result["precip_accum_amount"] is None
        assert result["precip_accum_unit"] is None
        assert result["precip_accum_name"] is None

    def test_absent_precipitation_block_all_none(self):
        """No precipitation block at all → all three fields None."""
        result = _parse_precip_accumulation({}, "en")
        assert result["precip_accum_amount"] is None
        assert result["precip_accum_unit"] is None
        assert result["precip_accum_name"] is None

    def test_amount_without_units_resolves_unit_none(self):
        """An amount with a value but no units → unit None (not {})."""
        period = {
            "precipitation": {
                "accumulation": {
                    "name": {"en": "rain"},
                    "amount": {"value": {"en": 2}},
                }
            }
        }
        result = _parse_precip_accumulation(period, "en")
        assert result["precip_accum_amount"] == 2.0
        assert result["precip_accum_unit"] is None
        assert result["precip_accum_name"] == "rain"
