"""Tests for WEonG coordinator refresh cascade.

Ensures that when the primary weather coordinator refreshes (via update_entity),
the WEonG coordinator also gets refreshed when a new model run is available.
The mixin uses needs_refresh() which is model-run-aware, not timer-based.
"""

from __future__ import annotations

import inspect

from ec_weather.coordinator.mixin import WEonGListenerMixin


class TestWEonGListenerMixinRefreshCascade:
    """Verify that WEonGListenerMixin triggers WEonG refresh on primary coordinator update."""

    def test_mixin_overrides_handle_coordinator_update(self) -> None:
        """The mixin must override _handle_coordinator_update to cascade refreshes."""
        assert hasattr(WEonGListenerMixin, "_handle_coordinator_update"), (
            "WEonGListenerMixin must override _handle_coordinator_update "
            "to trigger WEonG refresh when the primary coordinator updates"
        )

    def test_handle_coordinator_update_uses_needs_refresh(self) -> None:
        """_handle_coordinator_update must use needs_refresh() (model-run-aware)."""
        source = inspect.getsource(WEonGListenerMixin._handle_coordinator_update)
        assert "needs_refresh" in source, (
            "_handle_coordinator_update must use needs_refresh() which checks "
            "model run freshness, not just a timer-based is_fresh()"
        )

    def test_handle_coordinator_update_calls_super(self) -> None:
        """_handle_coordinator_update must call super() to preserve normal HA behavior."""
        source = inspect.getsource(WEonGListenerMixin._handle_coordinator_update)
        assert "super()" in source, (
            "_handle_coordinator_update must call super() to ensure "
            "the entity state write from CoordinatorEntity still happens"
        )

    def test_handle_coordinator_update_triggers_async_refresh(self) -> None:
        """_handle_coordinator_update must trigger async_request_refresh on stale WEonG."""
        source = inspect.getsource(WEonGListenerMixin._handle_coordinator_update)
        assert "async_request_refresh" in source, (
            "_handle_coordinator_update must call async_request_refresh() "
            "on the WEonG coordinator when data is stale"
        )

    def test_handle_coordinator_update_skips_polling_mode(self) -> None:
        """In polling mode, WEonG refreshes itself — don't double-trigger."""
        source = inspect.getsource(WEonGListenerMixin._handle_coordinator_update)
        assert "update_interval" in source, (
            "_handle_coordinator_update must check update_interval to skip "
            "the cascade when WEonG is in polling mode (it refreshes on its own schedule)"
        )
