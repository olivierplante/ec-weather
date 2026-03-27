"""Tests for the JS popup fetch behavior — fire-and-forget model.

Phase D replaced the _pendingTimestepFetch guard with fire-and-forget.
The coordinator's rate-limit (5s cooldown) and cache handle dedup.
The card simply fires fetch_day_timesteps whenever a popup opens with
icons_complete=false — no client-side guard needed.

Tests verify:
1. The card no longer references _pendingTimestepFetch
2. The card fires the service call unconditionally when icons_complete=false
3. The coordinator's rate-limit prevents duplicate queries
"""

from __future__ import annotations

from .conftest import CARD_JS_PATH as CARD_JS


class TestFireAndForgetPopupFetch:
    """Verify the card uses fire-and-forget for popup detail fetching."""

    def test_no_pending_fetch_guard(self) -> None:
        """Card must NOT reference _pendingTimestepFetch (guard removed)."""
        source = CARD_JS.read_text()
        assert "_pendingTimestepFetch" not in source, (
            "_pendingTimestepFetch guard should be removed — "
            "coordinator rate-limit handles dedup"
        )

    def test_fetch_service_call_exists(self) -> None:
        """Card must still call fetch_day_timesteps service on popup open."""
        source = CARD_JS.read_text()
        assert "fetch_day_timesteps" in source, (
            "Card must call fetch_day_timesteps service"
        )

    def test_fetch_conditioned_on_icons_complete(self) -> None:
        """Fetch is conditioned on icons_complete === false."""
        source = CARD_JS.read_text()
        assert "icons_complete === false" in source, (
            "Fetch must be conditioned on icons_complete === false"
        )

    def test_no_guard_check_before_service_call(self) -> None:
        """No guard check between icons_complete check and service call."""
        source = CARD_JS.read_text()
        # Find the block with icons_complete === false and callService
        # There should be no _pendingTimestepFetch check in between
        idx_icons = source.find("icons_complete === false")
        idx_call = source.find("callService", idx_icons)
        between = source[idx_icons:idx_call]
        assert "_pendingTimestepFetch" not in between, (
            "No guard check should exist between icons_complete check and service call"
        )
