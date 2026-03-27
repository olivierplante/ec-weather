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

# --- Config entry data matching a real Saint-Jérôme setup ---

MOCK_CONFIG_DATA = {
    "city_code": "qc-68",
    "city_name": "Saint-Jérôme",
    "language": "en",
    "lat": 45.78,
    "lon": -74.07,
    "bbox": "44.780,-75.070,46.780,-73.070",
    "geomet_bbox": "44.780,-75.070,46.780,-73.070",
    "aqhi_location_id": None,
}


def load_fixture(name: str) -> dict:
    """Load a JSON fixture file."""
    return json.loads((FIXTURES_DIR / name).read_text())
