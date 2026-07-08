"""Agreement tests: GEPS synthesis vs a WEonG-style reference (phase E1).

The 48-84h overlap window is covered by BOTH RDPS-WEonG (EC's own derivation)
and the GEPS ensemble. These tests pin ``synthesize_timestep``'s behaviour
against a WEonG-style reference for a set of synthetic meteorological regimes,
so a future threshold tweak that would tank real-world agreement fails CI.

They are NOT live comparisons: every value is synthetic (repo policy). Each
regime supplies a WEonG-side reading (fed through the same ``derive_icon`` path
the coordinator uses) and the matched GEPS percentile inputs, then asserts:

  - same wet/dry icon family (chance-of counts as wet-leaning),
  - dry regimes land in the same sky bucket (or an adjacent one),
  - wet regimes agree on precip type (rain vs snow),
  - temperature within tolerance,
  - POP in the same coarse band (low / chance / likely).

The classifiers (``icon_family``, ``is_wet_family``, ``pop_band``) live in
``extended_helpers`` beside the recipe they score, so this harness and the
dev-only live scorecard bucket both sides identically.
"""

from __future__ import annotations

import pytest

from ec_weather.coordinator.extended_helpers import (
    icon_family,
    is_wet_family,
    pop_band,
    synthesize_timestep,
)
from ec_weather.transforms import derive_icon
from ec_weather.timestamp_utils import hour_from_iso

# Release gate (spec "Validation harness"): sky agreement >= 80%, temp MAE
# <= 1.5 degC. The synthetic pairs below are all designed to agree, so the
# per-pair temp tolerance is the gate's MAE bound.
TEMP_TOLERANCE_C = 1.5

# Coarse dry-sky ladder for adjacency checks.
_DRY_LADDER = ["clear", "partly", "mostly", "cloudy"]

# Daytime and nighttime UTC hours for icon day/night variants.
DAY_TS = "2026-07-16T15:00:00Z"
NIGHT_TS = "2026-07-16T03:00:00Z"


def _weong_reference_icon(reference: dict, timestep_iso: str) -> int | None:
    """Derive the WEonG-side icon code for a synthetic reading."""
    icon_code, _condition = derive_icon(reference, hour_from_iso(timestep_iso))
    return icon_code


def _dry_buckets_adjacent(family_a: str, family_b: str) -> bool:
    """True when two dry sky families are equal or one step apart."""
    return abs(_DRY_LADDER.index(family_a) - _DRY_LADDER.index(family_b)) <= 1


# ---------------------------------------------------------------------------
# Regime table: (name, timestep, WEonG reference reading, GEPS inputs,
#                expected GEPS family, expected wet/dry, POP band)
# ---------------------------------------------------------------------------

# Each row is one meteorological regime. ``weong`` is the synthetic WEonG
# reading fed through derive_icon; ``geps`` are the matched GEPS percentile
# inputs fed through synthesize_timestep. ``expect_family`` pins the recipe's
# own output; the agreement assertions compare the two sides.
REGIMES: list[dict] = [
    {
        "name": "clear-summer-day",
        "ts": DAY_TS,
        "weong": {"sky_state": 1.0, "rain_mm": 0.0, "snow_cm": 0.0, "temp": 27.0},
        "weong_pop": 0,
        "geps": {"tt": 27.0, "hmx": 31.0, "nt": 12.0, "pop": 3, "rain": None, "snow": None},
        "expect_family": "clear",
        "expect_wet": False,
        "expect_pop_band": "low",
    },
    {
        "name": "overcast-cloudy-day",
        "ts": DAY_TS,
        "weong": {"sky_state": 10.0, "rain_mm": 0.0, "snow_cm": 0.0, "temp": 14.0},
        "weong_pop": 15,
        "geps": {"tt": 14.0, "hmx": None, "nt": 95.0, "pop": 18, "rain": None, "snow": None},
        "expect_family": "cloudy",
        "expect_wet": False,
        "expect_pop_band": "low",
    },
    {
        "name": "overcast-drizzle-day",
        # WEonG hour is raining a trace; GEPS reads a chance band. Both wet-rain.
        "ts": DAY_TS,
        "weong": {"sky_state": 9.0, "rain_mm": 0.4, "snow_cm": 0.0, "temp": 9.0},
        "weong_pop": 45,
        "geps": {"tt": 9.0, "hmx": None, "nt": 90.0, "pop": 45, "rain": 0.6, "snow": 0.0},
        "expect_family": "chance-rain",
        "expect_wet": True,
        "expect_pop_band": "chance",
    },
    {
        "name": "high-pop-rain-day",
        "ts": DAY_TS,
        "weong": {"sky_state": 8.0, "rain_mm": 5.0, "snow_cm": 0.0, "temp": 12.0},
        "weong_pop": 90,
        "geps": {"tt": 12.5, "hmx": None, "nt": 80.0, "pop": 85, "rain": 6.0, "snow": 0.0},
        "expect_family": "rain",
        "expect_wet": True,
        "expect_pop_band": "likely",
    },
    {
        "name": "snow-at-minus-5",
        "ts": DAY_TS,
        "weong": {"sky_state": 9.0, "rain_mm": 0.0, "snow_cm": 4.0, "temp": -5.0},
        "weong_pop": 80,
        "geps": {"tt": -4.5, "hmx": None, "nt": 88.0, "pop": 80, "rain": 0.0, "snow": 4.0},
        "expect_family": "snow",
        "expect_wet": True,
        "expect_pop_band": "likely",
    },
    {
        "name": "transition-0-2-snow",
        # Near-freezing wet regime; snow median dominates -> both call snow.
        "ts": DAY_TS,
        "weong": {"sky_state": 9.0, "rain_mm": 0.0, "snow_cm": 2.0, "temp": 1.0},
        "weong_pop": 70,
        "geps": {"tt": 1.5, "hmx": None, "nt": 85.0, "pop": 70, "rain": 0.5, "snow": 2.0},
        "expect_family": "snow",
        "expect_wet": True,
        "expect_pop_band": "likely",
    },
    {
        "name": "chance-band-rain-45",
        "ts": DAY_TS,
        "weong": {"sky_state": 7.0, "rain_mm": 0.3, "snow_cm": 0.0, "temp": 16.0},
        "weong_pop": 50,
        "geps": {"tt": 16.0, "hmx": None, "nt": 65.0, "pop": 45, "rain": 1.0, "snow": 0.0},
        "expect_family": "chance-rain",
        "expect_wet": True,
        "expect_pop_band": "chance",
    },
    {
        "name": "clear-night",
        "ts": NIGHT_TS,
        "weong": {"sky_state": 1.0, "rain_mm": 0.0, "snow_cm": 0.0, "temp": 15.0},
        "weong_pop": 5,
        "geps": {"tt": 15.5, "hmx": None, "nt": 15.0, "pop": 5, "rain": None, "snow": None},
        "expect_family": "clear",
        "expect_wet": False,
        "expect_pop_band": "low",
    },
    {
        "name": "rainy-night",
        "ts": NIGHT_TS,
        "weong": {"sky_state": 9.0, "rain_mm": 3.0, "snow_cm": 0.0, "temp": 10.0},
        "weong_pop": 75,
        "geps": {"tt": 9.5, "hmx": None, "nt": 90.0, "pop": 75, "rain": 4.0, "snow": 0.0},
        "expect_family": "rain",
        "expect_wet": True,
        "expect_pop_band": "likely",
    },
    {
        "name": "partly-cloudy-day",
        "ts": DAY_TS,
        "weong": {"sky_state": 5.0, "rain_mm": 0.0, "snow_cm": 0.0, "temp": 22.0},
        "weong_pop": 10,
        "geps": {"tt": 21.0, "hmx": None, "nt": 45.0, "pop": 10, "rain": None, "snow": None},
        "expect_family": "partly",
        "expect_wet": False,
        "expect_pop_band": "low",
    },
]


def _synthesize(regime: dict):
    geps = regime["geps"]
    return synthesize_timestep(
        regime["ts"],
        geps["tt"],
        geps["hmx"],
        geps["nt"],
        geps["pop"],
        geps["rain"],
        geps["snow"],
    )


@pytest.mark.parametrize("regime", REGIMES, ids=lambda r: r["name"])
class TestRegimeAgreement:
    def test_recipe_produces_expected_family(self, regime):
        """The GEPS recipe lands in the family the regime expects (pin)."""
        result = _synthesize(regime)
        assert icon_family(result.icon_code) == regime["expect_family"]

    def test_wet_dry_family_agrees(self, regime):
        """WEonG and GEPS agree on the wet/dry call for this regime."""
        geps = _synthesize(regime)
        ref_icon = _weong_reference_icon(regime["weong"], regime["ts"])
        assert is_wet_family(icon_family(geps.icon_code)) == regime["expect_wet"]
        assert is_wet_family(icon_family(ref_icon)) == regime["expect_wet"]

    def test_dry_sky_bucket_matches_or_adjacent(self, regime):
        """Dry regimes land in the same sky bucket or an adjacent one."""
        if regime["expect_wet"]:
            pytest.skip("wet regime — sky bucket not compared")
        geps_family = icon_family(_synthesize(regime).icon_code)
        ref_family = icon_family(_weong_reference_icon(regime["weong"], regime["ts"]))
        assert _dry_buckets_adjacent(ref_family, geps_family)

    def test_wet_precip_type_agrees(self, regime):
        """Wet regimes agree on rain vs snow (chance-of typed the same way)."""
        if not regime["expect_wet"]:
            pytest.skip("dry regime — precip type not compared")
        geps_family = icon_family(_synthesize(regime).icon_code)
        ref_family = icon_family(_weong_reference_icon(regime["weong"], regime["ts"]))
        geps_is_snow = "snow" in geps_family
        ref_is_snow = "snow" in ref_family
        assert geps_is_snow == ref_is_snow

    def test_temp_within_tolerance(self, regime):
        """GEPS median temp is within the release-gate tolerance of WEonG."""
        geps = _synthesize(regime)
        assert geps.temp is not None
        assert abs(geps.temp - regime["weong"]["temp"]) <= TEMP_TOLERANCE_C

    def test_pop_in_expected_band(self, regime):
        """GEPS and WEonG POP fall in the same coarse band."""
        geps = _synthesize(regime)
        assert pop_band(geps.pop) == regime["expect_pop_band"]
        assert pop_band(regime["weong_pop"]) == regime["expect_pop_band"]


# ---------------------------------------------------------------------------
# icon_family / is_wet_family / pop_band unit behaviour
# ---------------------------------------------------------------------------

class TestIconFamily:
    @pytest.mark.parametrize(
        "code,family",
        [
            (0, "clear"), (1, "clear"), (30, "clear"), (31, "clear"),
            (2, "partly"), (32, "partly"),
            (3, "mostly"), (33, "mostly"),
            (10, "cloudy"),
            (12, "rain"), (13, "rain"), (14, "rain"),
            (17, "snow"), (16, "snow"), (18, "snow"), (27, "snow"),
            (6, "chance-rain"),
            (8, "chance-snow"),
            (15, "mixed"),
            (None, None),
        ],
    )
    def test_classification(self, code, family):
        assert icon_family(code) == family


class TestIsWetFamily:
    @pytest.mark.parametrize(
        "family,wet",
        [
            ("clear", False), ("partly", False), ("mostly", False),
            ("cloudy", False),
            ("rain", True), ("snow", True),
            ("chance-rain", True), ("chance-snow", True),
            ("mixed", True),
            (None, False),
        ],
    )
    def test_wet_flag(self, family, wet):
        assert is_wet_family(family) is wet


class TestPopBand:
    @pytest.mark.parametrize(
        "pop,band",
        [
            (0, "low"), (29, "low"), (29.9, "low"),
            (30, "chance"), (45, "chance"), (59, "chance"),
            (60, "likely"), (85, "likely"), (100, "likely"),
            (None, None),
        ],
    )
    def test_bands(self, pop, band):
        assert pop_band(pop) == band


# ---------------------------------------------------------------------------
# Documented tolerated-divergence zone (why the gate is < 100%)
# ---------------------------------------------------------------------------

class TestChanceBandDivergence:
    """The 30-59 chance band is the honest wet/dry disagreement zone.

    GEPS hedges to a chance-of icon (wet-leaning) while a given WEonG hour may
    read dry (no accumulation that hour). This is expected and is exactly why
    the release gate is 80%, not 100% — documented here so a reader knows the
    band is a tolerated divergence, not a bug.
    """

    def test_chance_geps_vs_dry_weong_disagree(self):
        geps = synthesize_timestep(DAY_TS, 15.0, None, 65.0, 45, 1.0, 0.0)
        # A WEonG hour with no accumulation and broken cloud reads dry.
        ref_icon = _weong_reference_icon(
            {"sky_state": 6.0, "rain_mm": 0.0, "snow_cm": 0.0, "temp": 15.0},
            DAY_TS,
        )
        assert is_wet_family(icon_family(geps.icon_code)) is True
        assert is_wet_family(icon_family(ref_icon)) is False
