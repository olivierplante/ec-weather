"""OnDemandCoordinator — base class with freshness-check pattern."""

from __future__ import annotations

import time
from datetime import timedelta

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ..api_client import FetchError


class OnDemandCoordinator(DataUpdateCoordinator):
    """DataUpdateCoordinator with on-demand freshness gating.

    When *polling* is False the coordinator has no ``update_interval`` and
    relies on explicit ``async_request_refresh()`` calls (typically from
    ``async_update`` in entities). The ``is_fresh()`` / ``mark_refreshed()``
    pair lets subclasses skip redundant API calls when data is still within
    the configured interval.
    """

    def __init__(
        self,
        hass,
        logger,
        *,
        name: str,
        interval: timedelta,
        polling: bool,
    ) -> None:
        super().__init__(
            hass,
            logger,
            name=name,
            update_interval=interval if polling else None,
        )
        self._polling = polling
        self._configured_interval = interval
        self._last_refresh_ts: float | None = None

    def is_fresh(self) -> bool:
        """Return True if data is still fresh (skip re-fetch)."""
        if self._polling:
            return False
        if not self.data or not self._last_refresh_ts:
            return False
        elapsed = time.monotonic() - self._last_refresh_ts
        return elapsed < self._configured_interval.total_seconds()

    def mark_refreshed(self) -> None:
        """Record the current monotonic timestamp as last-refresh time."""
        self._last_refresh_ts = time.monotonic()

    async def _async_update_data(self) -> dict:
        """Wrap subclass update to convert FetchError → UpdateFailed.

        HA's DataUpdateCoordinator expects UpdateFailed for graceful error
        handling. api_client.py raises FetchError (no HA dependency).
        This bridge converts between the two layers.
        """
        try:
            return await self._do_update()
        except FetchError as err:
            raise UpdateFailed(str(err)) from err

    async def _do_update(self) -> dict:
        """Override in subclasses instead of _async_update_data."""
        raise NotImplementedError
