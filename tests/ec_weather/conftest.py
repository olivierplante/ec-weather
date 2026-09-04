"""Fixtures for EC Weather integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import ec_weather
from ec_weather.const import DOMAIN

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Resolve the JS card file from the ec_weather package location.
# Works in both local (config/custom_components/ec_weather/) and
# CI (custom_components/ec_weather/) directory layouts.
CARD_JS_PATH = Path(ec_weather.__file__).parent / "www" / "ec-weather-card.js"

# Resolve the entities doc from either of two layouts. On the monorepo it
# sits next to the package (config/custom_components/ec_weather/docs/). On
# the public repo it does not: .hacsignore excludes docs/ from the installed
# payload, and the release script copies docs/ to the repo root instead, two
# levels above the package (custom_components/ec_weather/).
_ENTITIES_DOCS_CANDIDATES = (
    Path(ec_weather.__file__).parent / "docs" / "entities.md",
    Path(ec_weather.__file__).parents[2] / "docs" / "entities.md",
)
ENTITIES_DOCS_PATH = next(
    (candidate for candidate in _ENTITIES_DOCS_CANDIDATES if candidate.exists()),
    _ENTITIES_DOCS_CANDIDATES[0],
)

# --- Config entry data for tests (Ottawa area) ---

MOCK_CONFIG_DATA = {
    "city_code": "on-118",
    "city_name": "Ottawa",
    "language": "en",
    "lat": 45.42,
    "lon": -75.70,
    "bbox": "44.420,-76.700,46.420,-74.700",
    "geomet_bbox": "44.420,-76.700,46.420,-74.700",
    "aqhi_location_id": None,
}


def load_fixture(name: str) -> dict:
    """Load a JSON fixture file."""
    return json.loads((FIXTURES_DIR / name).read_text())
