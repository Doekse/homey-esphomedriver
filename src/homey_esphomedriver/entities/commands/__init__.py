"""Homey capability listeners that issue ESPHome Native API commands."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from homey_esphomedriver.entities.commands.alarm_control_panel import (
    AlarmControlPanelEntityCommandHandler,
)
from homey_esphomedriver.entities.commands.base import AbstractEntityCommandHandler
from homey_esphomedriver.entities.commands.climate import ClimateEntityCommandHandler
from homey_esphomedriver.entities.commands.cover import CoverEntityCommandHandler
from homey_esphomedriver.entities.commands.fan import FanEntityCommandHandler
from homey_esphomedriver.entities.commands.generic import GenericEntityCommandHandler
from homey_esphomedriver.entities.commands.light import LightEntityCommandHandler
from homey_esphomedriver.entities.commands.lock import LockEntityCommandHandler
from homey_esphomedriver.entities.commands.media_player import (
    MediaPlayerEntityCommandHandler,
)
from homey_esphomedriver.entities.commands.valve import ValveEntityCommandHandler
from homey_esphomedriver.entities.commands.water_heater import (
    WaterHeaterEntityCommandHandler,
)

if TYPE_CHECKING:
    from homey.device import CapabilityListener

    from homey_esphomedriver.esphome_device import EspHomeDevice


class DeviceEntityCommandHandler:
    """Owns Homey capability listeners that issue Native API commands."""

    def __init__(self, device: EspHomeDevice) -> None:
        self._device = device
        self._handlers: dict[str, tuple[AbstractEntityCommandHandler, str]] = {}
        self._multi: list[tuple[tuple[str, ...], CapabilityListener]] = []

        for handler in (
            AlarmControlPanelEntityCommandHandler(device),
            ClimateEntityCommandHandler(device),
            CoverEntityCommandHandler(device),
            FanEntityCommandHandler(device),
            GenericEntityCommandHandler(device),
            LightEntityCommandHandler(device),
            LockEntityCommandHandler(device),
            MediaPlayerEntityCommandHandler(device),
            ValveEntityCommandHandler(device),
            WaterHeaterEntityCommandHandler(device),
        ):
            for capability_id in handler.CAPABILITIES:
                self._handlers[capability_id] = (handler, capability_id)
            for caps, method_name in handler.MULTI_CAPABILITIES:
                self._multi.append((caps, getattr(handler, method_name)))

    def register_listeners(self) -> None:
        """Wire Homey listeners for every capability currently on the device."""
        for capability_id in self._device.get_capabilities():
            self.register_listener_for_capability(capability_id)

    def register_listener_for_capability(self, capability_id: str) -> None:
        """Wire the Homey listener for one settable capability, if any."""
        resolved = self._resolve(capability_id)
        if resolved is not None:
            handler, method_name = resolved
            self._device.register_capability_listener(
                capability_id,
                self._listener_with_capability_id(
                    getattr(handler, method_name),
                    capability_id,
                    pass_value=method_name not in handler.VALUELESS_CAPABILITIES,
                ),
            )

        for caps, listener in self._multi:
            if capability_id not in caps:
                continue
            if not all(self._device.has_capability(cap) for cap in caps):
                continue
            self._device.register_multiple_capability_listener(list(caps), listener)

    def _resolve(
        self, capability_id: str
    ) -> tuple[AbstractEntityCommandHandler, str] | None:
        """Return ``(handler, method_name)`` for ``capability_id``, if any."""
        # WORKAROUND: get_capability_options raises on stored null
        # (Athom will return {}).
        options = self._device._capabilities_options.get(capability_id) or {}
        if capability_id == "onoff" or capability_id.startswith("onoff."):
            return self._handlers.get("onoff")
        if capability_id.startswith(("button.", "restart", "identify")):
            # Remap is button.refresh, so the button.* prefix is not enough.
            if options.get("key") is None:
                return None
            return self._handlers.get("button")
        if capability_id.startswith("esphome_number."):
            if not options.get("setable", False):
                return None
            return self._handlers.get("number")
        if capability_id.startswith("esphome_select."):
            return self._handlers.get("select")
        resolved = self._handlers.get(capability_id)
        if resolved is None:
            return None
        handler, _method_name = resolved
        if handler.REQUIRE_ENTITY_TYPE:
            entity_type = options.get("entity_type")
            if entity_type != handler.ENTITY_TYPE:
                return None
        return resolved

    def _listener_with_capability_id(
        self,
        handler: Callable[..., Awaitable[None]],
        capability_id: str,
        *,
        pass_value: bool = True,
    ) -> CapabilityListener:
        """Bind ``capability_id`` so one handler can serve indexed capabilities."""
        if pass_value:

            async def listener(value: Any, **_kwargs: Any) -> None:
                await handler(value, capability_id=capability_id)

            return listener

        async def listener(_value: Any = True, **_kwargs: Any) -> None:
            await handler(capability_id=capability_id)

        return listener
