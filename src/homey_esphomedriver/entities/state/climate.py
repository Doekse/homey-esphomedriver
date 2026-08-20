"""Push ESPHome ClimateState into Homey climate capabilities."""

from __future__ import annotations

from typing import cast

from aioesphomeapi import (
    ClimateFanMode,
    ClimateMode,
    ClimatePreset,
    ClimateState,
    ClimateSwingMode,
    EntityState,
)

from homey_esphomedriver.entities.state.base import (
    AbstractEntityStateUpdateHandler,
)
from homey_esphomedriver.units import convert_units

_THERMOSTAT_MODE = {
    ClimateMode.HEAT: "heat",
    ClimateMode.COOL: "cool",
    ClimateMode.HEAT_COOL: "auto",
    ClimateMode.AUTO: "auto",
    ClimateMode.OFF: "off",
    ClimateMode.DRY: "dry",
    ClimateMode.FAN_ONLY: "fan_only",
}

_FAN_MODE = {
    ClimateFanMode.ON: "on",
    ClimateFanMode.OFF: "off",
    ClimateFanMode.AUTO: "auto",
    ClimateFanMode.LOW: "low",
    ClimateFanMode.MEDIUM: "medium",
    ClimateFanMode.HIGH: "high",
    ClimateFanMode.MIDDLE: "middle",
    ClimateFanMode.FOCUS: "focus",
    ClimateFanMode.DIFFUSE: "diffuse",
    ClimateFanMode.QUIET: "quiet",
}

_PRESET = {
    ClimatePreset.NONE: "none",
    ClimatePreset.HOME: "home",
    ClimatePreset.AWAY: "away",
    ClimatePreset.BOOST: "boost",
    ClimatePreset.COMFORT: "comfort",
    ClimatePreset.ECO: "eco",
    ClimatePreset.SLEEP: "sleep",
    ClimatePreset.ACTIVITY: "activity",
}


class ClimateEntityStateUpdateHandler(AbstractEntityStateUpdateHandler):
    async def handle(self, state: EntityState, capabilities: list[str]) -> None:
        climate = cast(ClimateState, state)

        onoff_id = self.find_capability(capabilities, "onoff")
        if onoff_id is not None:
            self.set_capability_value(onoff_id, climate.mode != ClimateMode.OFF)

        mode_id = self.find_capability(capabilities, "thermostat_mode")
        if mode_id is not None:
            self.set_capability_value(
                mode_id,
                _THERMOSTAT_MODE.get(climate.mode, "off"),
            )

        for base, value in (
            ("measure_temperature", climate.current_temperature),
            ("target_temperature", climate.target_temperature),
            ("target_temperature_min", climate.target_temperature_low),
            ("target_temperature_max", climate.target_temperature_high),
        ):
            capability_id = self.find_capability(capabilities, base)
            if capability_id is not None:
                self.set_capability_value(
                    capability_id,
                    convert_units(self.device, capability_id, float(value)),
                )

        humidity_id = self.find_capability(capabilities, "measure_humidity")
        if humidity_id is not None:
            self.set_capability_value(humidity_id, float(climate.current_humidity))

        target_humidity_id = self.find_capability(capabilities, "target_humidity")
        if target_humidity_id is not None:
            self.set_capability_value(
                target_humidity_id,
                float(climate.target_humidity),
            )

        fan_mode_id = self.find_capability(capabilities, "fan_mode")
        if fan_mode_id is not None:
            value = climate.custom_fan_mode or _FAN_MODE.get(climate.fan_mode)
            options = self.device.get_capability_options(fan_mode_id).get("values", [])
            if value in {item["id"] for item in options}:
                self.set_capability_value(fan_mode_id, value)

        swing_id = self.find_capability(capabilities, "swing_mode")
        if swing_id is not None:
            match climate.swing_mode:
                case ClimateSwingMode.BOTH:
                    self.set_capability_value(swing_id, "both")
                case ClimateSwingMode.HORIZONTAL:
                    self.set_capability_value(swing_id, "horizontal")
                case ClimateSwingMode.VERTICAL:
                    self.set_capability_value(swing_id, "vertical")
                case _:
                    self.set_capability_value(swing_id, "off")

        preset_id = self.find_capability(capabilities, "thermostat_preset")
        if preset_id is not None:
            if climate.custom_preset:
                self.set_capability_value(preset_id, climate.custom_preset)
            elif climate.preset is not None:
                self.set_capability_value(
                    preset_id,
                    _PRESET.get(climate.preset, "none"),
                )
