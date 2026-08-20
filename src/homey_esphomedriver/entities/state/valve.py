"""Push ESPHome ValveState into Homey valve capabilities."""

from __future__ import annotations

from typing import cast

from aioesphomeapi import EntityState, ValveState

from homey_esphomedriver.entities.state.base import (
    AbstractEntityStateUpdateHandler,
)


class ValveEntityStateUpdateHandler(AbstractEntityStateUpdateHandler):
    async def handle(self, state: EntityState, capabilities: list[str]) -> None:
        valve = cast(ValveState, state)

        onoff_id = self.find_capability(capabilities, "onoff")
        if onoff_id is not None:
            # Homey onoff is open; ESPHome position 0.0 is closed.
            self.handle_on_off(valve.position != 0.0, onoff_id)

        position_id = self.find_capability(capabilities, "valve_position")
        if position_id is not None:
            # No scale conversion: ESPHome position is already Homey's 0.0–1.0 range.
            self.set_capability_value(position_id, float(valve.position))
