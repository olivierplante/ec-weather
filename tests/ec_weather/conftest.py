"""Fixtures for EC Weather integration tests."""

from __future__ import annotations

import json
from pathlib import Path

from ec_weather.const import DOMAIN

FIXTURES_DIR = Path(__file__).parent / "fixtures"

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
