"""Tests for EC Weather models — device_info and typed runtime data."""

from __future__ import annotations

from ec_weather.const import DOMAIN
from ec_weather.models import ECWeatherData, build_device_info


def test_build_device_info_identifiers():
    """Device info uses (DOMAIN, city_code) as identifier."""
    info = build_device_info("qc-68", "Saint-Jérôme")
    assert info["identifiers"] == {(DOMAIN, "qc-68")}


def test_build_device_info_name():
    """Device info name includes the city name."""
    info = build_device_info("qc-68", "Saint-Jérôme")
    assert "Saint-Jérôme" in info["name"]


def test_build_device_info_shared_identifiers():
    """Two calls with the same city_code produce the same identifiers."""
    info1 = build_device_info("qc-68", "Saint-Jérôme")
    info2 = build_device_info("qc-68", "Saint-Jérôme")
    assert info1["identifiers"] == info2["identifiers"]


def test_build_device_info_different_cities():
    """Different city codes produce different identifiers."""
    info1 = build_device_info("qc-68", "Saint-Jérôme")
    info2 = build_device_info("on-143", "Toronto")
    assert info1["identifiers"] != info2["identifiers"]


def test_build_device_info_manufacturer():
    """Device info lists Environment Canada as manufacturer."""
    info = build_device_info("qc-68", "Saint-Jérôme")
    assert info["manufacturer"] == "Environment and Climate Change Canada"


def test_ec_weather_data_dataclass():
    """ECWeatherData stores coordinator references as typed attributes."""
    # Use sentinel objects to verify attribute access works
    w, a, q, g = object(), object(), object(), object()
    data = ECWeatherData(weather=w, alerts=a, aqhi=q, weong=g)
    assert data.weather is w
    assert data.alerts is a
    assert data.aqhi is q
    assert data.weong is g
