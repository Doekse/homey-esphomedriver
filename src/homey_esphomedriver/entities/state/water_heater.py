"""Push ESPHome WaterHeaterState into Homey waterheater capabilities."""

from __future__ import annotations

from typing import cast

from aioesphomeapi import (
    EntityState,
    WaterHeaterMode,
    WaterHeaterState,
    WaterHeaterStateFlag,
)

from homey_esphomedriver.entities.state.base import (
    AbstractEntityStateUpdateHandler,
)
from homey_esphomedriver.units import convert_units

_MODE_TO_HOMEY = {
    WaterHeaterMode.OFF: "off",
    WaterHeaterMode.ECO: "eco",
    WaterHeaterMode.ELECTRIC: "electric",
    WaterHeaterMode.PERFORMANCE: "performance",
    WaterHeaterMode.HIGH_DEMAND: "high_demand",
    WaterHeaterMode.HEAT_PUMP: "heat_pump",
    WaterHeaterMode.GAS: "gas",
}


class WaterHeaterEntityStateUpdateHandler(AbstractEntityStateUpdateHandler):
    async def handle(self, state: EntityState, capabilities: list[str]) -> None:
        heater = cast(WaterHeaterState, state)

        onoff_id = self.find_capability(capabilities, "onoff")
        if onoff_id is not None:
            self.set_capability_value(
                onoff_id,
                bool(heater.state & WaterHeaterStateFlag.ON),
            )

        mode_id = self.find_capability(capabilities, "heater_operation_mode")
        if mode_id is not None and heater.mode is not None:
            self.set_capability_value(
                mode_id,
                _MODE_TO_HOMEY.get(heater.mode, "off"),
            )

        for base, value in (
            ("measure_temperature", heater.current_temperature),
            ("target_temperature", heater.target_temperature),
            ("target_temperature_min", heater.target_temperature_low),
            ("target_temperature_max", heater.target_temperature_high),
        ):
            capability_id = self.find_capability(capabilities, base)
            if capability_id is not None:
                self.set_capability_value(
                    capability_id,
                    convert_units(self.device, capability_id, float(value)),
                )
