"""Push ESPHome BinarySensorState into Homey alarm and boolean capabilities."""

from __future__ import annotations

from typing import cast

from aioesphomeapi import BinarySensorState, EntityState

from homey_esphomedriver.entities.state.base import (
    AbstractEntityStateUpdateHandler,
)

# Homey treats these as "closed/locked/connected" while ESPHome reports the
# opposite polarity for the matching device classes.
_INVERTED_CAPABILITIES = [
    "alarm_connectivity",
    "garagedoor_closed",
    "locked",
]


class BinarySensorEntityStateUpdateHandler(AbstractEntityStateUpdateHandler):
    async def handle(self, state: EntityState, capabilities: list[str]) -> None:
        capability = capabilities[0]
        binary = cast(BinarySensorState, state)
        if binary.missing_state:
            self.set_capability_value(capability, None)
            return

        base = capability.split(".", 1)[0]

        if base == "battery_charging_state":
            self.set_capability_value(
                capability,
                "charging" if binary.state else "idle",
            )
            return

        self.handle_on_off(
            bool(binary.state),
            capability,
            invert=base in _INVERTED_CAPABILITIES,
        )
