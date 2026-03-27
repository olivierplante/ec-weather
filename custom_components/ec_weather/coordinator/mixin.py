"""WEonGListenerMixin — shared by entities that depend on two coordinators."""

from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)


class WEonGListenerMixin:
    """Mixin for entities that listen to both a weather and WEonG coordinator.

    The entity's primary coordinator is registered automatically by HA's
    CoordinatorEntity. This mixin adds a second listener for the WEonG
    coordinator so the entity re-renders when precipitation data updates.

    It also triggers a WEonG refresh when the primary (weather) coordinator
    refreshes and the WEonG data is stale. This ensures on-demand mode
    users get fresh WEonG data when they view the dashboard, since
    update_entity only refreshes the primary coordinator.

    Subclasses must store the WEonG coordinator as ``self._weong_coordinator``.
    """

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self._weong_coordinator.async_add_listener(
                self._handle_weong_update
            )
        )

    def _handle_coordinator_update(self) -> None:
        """Called when the primary (weather) coordinator updates.

        If the WEonG coordinator needs a refresh (new model run available
        or no data), trigger a background fetch. Skipped in polling mode
        where update_interval handles scheduling.
        """
        super()._handle_coordinator_update()
        weong = self._weong_coordinator
        if weong.needs_refresh() and weong.update_interval is None:
            _LOGGER.debug("WEonG new model run available — triggering refresh")
            self.hass.async_create_task(weong.async_request_refresh())

    def _handle_weong_update(self) -> None:
        self.async_write_ha_state()
