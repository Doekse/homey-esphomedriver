"""Push ESPHome Event values into Homey event capabilities."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from aioesphomeapi import EntityState, Event

from homey_esphomedriver.entities.state.base import (
    AbstractEntityStateUpdateHandler,
)
from homey_esphomedriver.esphome_util import format_event_type

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

    def handle(self, state: EntityState, capabilities: list[str]) -> None:
        capability = capabilities[0]
        event = cast(Event, state)
        event_type = str(event.event_type)
        self._cancel_idle(capability)

        if capability.startswith("alarm_doorbell."):
            self._set_capability_value_only(capability, True)
            self._trigger_then_idle(capability, None, False, _DOORBELL_IDLE_DELAY_MS)
            return

        self._set_capability_value_only(capability, event_type)
        self._trigger_then_idle(
            capability,
            format_event_type(event_type),
            _IDLE,
            _BUTTON_IDLE_DELAY_MS,
        )

    def _trigger_then_idle(
        self,
        capability_id: str,
        value: Any,
        idle_value: Any,
        delay_ms: int,
    ) -> None:
        """Fire the Flow card, then start the idle timer once it has run."""
        task = asyncio.ensure_future(
            self._async_trigger_then_idle(capability_id, value, idle_value, delay_ms)
        )
        task.add_done_callback(self._on_set_capability_done)

    async def _async_trigger_then_idle(
        self,
        capability_id: str,
        value: Any,
        idle_value: Any,
        delay_ms: int,
    ) -> None:
        await self._flow.trigger_event(self.device, capability_id, value)
        self._schedule_idle(capability_id, idle_value, delay_ms)

    def _set_capability_value_only(self, capability_id: str, value: Any) -> None:
        """Write capability state without firing Flow cards."""
        task = asyncio.ensure_future(
            self.device.set_capability_value(capability_id, value)
        )
        task.add_done_callback(self._on_set_capability_done)

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
