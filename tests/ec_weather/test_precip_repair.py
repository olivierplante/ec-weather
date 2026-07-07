"""Tests for the yesterday-precip repair prompt gating (issue #9, Part B).

Existing users won't know the feature exists. On setup we raise a fixable
HA repair issue inviting them to configure it — but only when:
  - no precipitation station is configured, AND
  - we haven't already run discovery for this entry (so we don't re-probe the
    API or re-nag on every restart).

``should_offer_precip_repair`` is the pure predicate; the actual issue
creation and repair flow are thin HA wrappers around it.
"""

from __future__ import annotations

from ec_weather.repairs import should_offer_precip_repair
from ec_weather.const import (
    CONF_PRECIP_DISCOVERED,
    CONF_PRECIP_STATION_ID,
)


class TestShouldOfferPrecipRepair:
    def test_offers_when_unconfigured_and_not_discovered(self):
        assert should_offer_precip_repair({}) is True

    def test_not_offered_when_station_configured(self):
        data = {CONF_PRECIP_STATION_ID: "7025251"}
        assert should_offer_precip_repair(data) is False

    def test_not_offered_when_already_discovered(self):
        """User already saw the chooser (and opted out) → don't nag again."""
        data = {CONF_PRECIP_DISCOVERED: True}
        assert should_offer_precip_repair(data) is False

    def test_not_offered_when_configured_even_if_not_flagged(self):
        data = {CONF_PRECIP_STATION_ID: "7025251", CONF_PRECIP_DISCOVERED: False}
        assert should_offer_precip_repair(data) is False
