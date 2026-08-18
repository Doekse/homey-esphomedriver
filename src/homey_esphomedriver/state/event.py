"""Push ESPHome Event values into Homey event capabilities."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from aioesphomeapi import EntityState, Event

from homey_esphomedriver.esphome_util import format_event_type
from homey_esphomedriver.state.base import (
    AbstractEntityStateUpdateHandler,
)

_BUTTON_IDLE_DELAY_MS = 1000
_DOORBELL_IDLE_DELAY_MS = 5000
_IDLE = "idle"


class EventEntityStateUpdateHandler(AbstractEntityStateUpdateHandler):
    def __init__(self, device: Any) -> None:
        super().__init__(device)
        self._idle_timeouts: dict[str, int] = {}

    def uninit(self) -> None:
        for timeout_id in self._idle_timeouts.values():
            self.device.homey.clear_timeout(timeout_id)
        self._idle_timeouts.clear()

    async def handle(self, state: EntityState, capabilities: list[str]) -> None:
        capability = capabilities[0]
        event = cast(Event, state)
        event_type = str(event.event_type)
        self._cancel_idle(capability)

        if capability.startswith("alarm_doorbell."):
            self._set_capability_value_only(capability, True)
            await self._fire_doorbell(capability)
            self._schedule_idle(capability, False, _DOORBELL_IDLE_DELAY_MS)
            return

        if capability.startswith("event_button."):
            self._set_capability_value_only(capability, event_type)
            await self._fire_button(capability, event_type)
            self._schedule_idle(capability, _IDLE, _BUTTON_IDLE_DELAY_MS)
            return

        self._set_capability_value_only(capability, event_type)
        await self._fire_generic(capability, event_type)
        self._schedule_idle(capability, _IDLE, _BUTTON_IDLE_DELAY_MS)

    def _set_capability_value_only(self, capability_id: str, value: Any) -> None:
        """Write capability state without firing Flow cards."""
        task = asyncio.ensure_future(
            self.device.set_capability_value(capability_id, value)
        )
        task.add_done_callback(self._on_set_capability_done)

    async def _fire_button(self, capability_id: str, event_type: str) -> None:
        await self._esphome_driver().trigger_event_button_received(
            self.device,
            format_event_type(event_type),
            self._capability_title(capability_id),
        )

    async def _fire_doorbell(self, capability_id: str) -> None:
        await self._esphome_driver().trigger_alarm_doorbell_received(
            self.device,
            self._capability_title(capability_id),
        )

    async def _fire_generic(self, capability_id: str, event_type: str) -> None:
        await self._esphome_driver().trigger_event_generic_received(
            self.device,
            format_event_type(event_type),
            self._capability_title(capability_id),
        )

    def _schedule_idle(
        self,
        capability_id: str,
        idle_value: Any,
        delay_ms: int,
    ) -> None:
        self._cancel_idle(capability_id)

        def on_idle() -> None:
            self._idle_timeouts.pop(capability_id, None)
            self._set_capability_value_only(capability_id, idle_value)

        self._idle_timeouts[capability_id] = self.device.homey.set_timeout(
            on_idle,
            delay_ms,
        )

    def _cancel_idle(self, capability_id: str) -> None:
        timeout_id = self._idle_timeouts.pop(capability_id, None)
        if timeout_id is not None:
            self.device.homey.clear_timeout(timeout_id)
