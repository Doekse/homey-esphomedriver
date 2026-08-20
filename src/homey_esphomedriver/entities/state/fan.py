"""Push ESPHome FanState into Homey fan capabilities."""

from __future__ import annotations

from typing import cast

from aioesphomeapi import EntityState, FanState

from homey_esphomedriver.entities.state.base import (
    AbstractEntityStateUpdateHandler,
)


class FanEntityStateUpdateHandler(AbstractEntityStateUpdateHandler):
    async def handle(self, state: EntityState, capabilities: list[str]) -> None:
        fan = cast(FanState, state)

        onoff_id = self.find_capability(capabilities, "onoff")
        if onoff_id is not None:
            self.handle_on_off(fan.state, onoff_id)

        speed_id = self.find_capability(capabilities, "fan_speed")
        if speed_id is not None:
            speed_count = int(
                self.device.get_capability_options(speed_id)["speed_count"]
            )
            self.set_capability_value(speed_id, float(fan.speed_level) / speed_count)

        oscillate_id = self.find_capability(capabilities, "fan_oscillate")
        if oscillate_id is not None:
            self.set_capability_value(oscillate_id, bool(fan.oscillating))

        preset = (fan.preset_mode or "").lower()
        if not preset:
            return

        for base in ("fan_mode", "aircleaner_mode"):
            mode_id = self.find_capability(capabilities, base)
            if mode_id is not None:
                self.set_capability_value(mode_id, preset)
                return
