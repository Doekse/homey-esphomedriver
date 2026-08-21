"""Shared helpers for pushing ESPHome entity states into Homey capabilities."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from aioesphomeapi import EntityState

from homey_esphomedriver.esphome_util import debug_log

if TYPE_CHECKING:
    from homey.device import Device

    from homey_esphomedriver.flow import DriverFlowHandler


class AbstractEntityStateUpdateHandler:
    """Base with capability I/O helpers used by concrete entity handlers."""

    def __init__(self, device: Device) -> None:
        self.device = device

    async def handle(self, state: EntityState, capabilities: list[str]) -> None:
        """Apply ``state`` to the Homey capabilities bound to this entity.

        Args:
            state: Latest Native API entity state.
            capabilities: Capability ids stored against ``state.key``.
        """
        raise NotImplementedError

    def uninit(self) -> None:
        """Release timers or other handler resources. Override when needed."""

    def has_capability(self, capability_id: str) -> bool:
        return self.device.has_capability(capability_id)

    def find_capability(self, capabilities: list[str], base: str) -> str | None:
        """Return the mapped capability whose id is ``base`` or ``base.<suffix>``."""
        for capability in capabilities:
            if capability == base or capability.startswith(f"{base}."):
                return capability
        return None

    def set_capability_value(self, capability_id: str, value: Any) -> None:
        """Write a capability without awaiting.

        Also fires base ``esphome_*`` Flow cards for sub-capabilities. Homey only
        auto-triggers ``<full_id>_changed`` (e.g. ``esphome_number.foo_changed``),
        which cannot be declared for dynamic object IDs at compose time.
        """
        if not self.has_capability(capability_id):
            self.error(f"Unavailable capability requested: {capability_id}")
            return

        previous = self.device.get_capability_value(capability_id)
        task = asyncio.ensure_future(
            self._set_capability_value_and_trigger(capability_id, value, previous)
        )
        task.add_done_callback(self._on_set_capability_done)

    async def _set_capability_value_and_trigger(
        self,
        capability_id: str,
        value: Any,
        previous: Any,
    ) -> None:
        await self.device.set_capability_value(capability_id, value)
        if previous == value:
            return
        await self._flow.trigger_subcapability(self.device, capability_id, value)

    @property
    def _flow(self) -> DriverFlowHandler:
        return self.device.driver._flow  # type: ignore[attr-defined,no-any-return]

    def handle_on_off(
        self,
        state: bool,
        capability: str,
        invert: bool = False,
    ) -> None:
        """Apply a boolean ESPHome state to an onoff/alarm capability."""
        self.set_capability_value(capability, (not state) if invert else state)

    def log(self, *args: object) -> None:
        self.device.log(*args)

    def debug(self, *args: object) -> None:
        debug_log(self.device.log, *args)

    def error(self, *args: object) -> None:
        self.device.error(*args)

    def _on_set_capability_done(self, task: asyncio.Future[Any]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            self.error(error)
