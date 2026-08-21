"""Push ESPHome LightState into Homey light capabilities.

ESPHome brightness and RGB are 0–1 and color temperature is mireds. Homey
dim/hue/sat are 0–1, and ``light_temperature`` is inverted across the stored
kelvin range.
"""

from __future__ import annotations

import colorsys
from typing import cast

from aioesphomeapi import ColorMode, EntityState, LightState

from homey_esphomedriver.entities.state.base import (
    AbstractEntityStateUpdateHandler,
)
from homey_esphomedriver.units import mireds_to_kelvin


class LightEntityStateUpdateHandler(AbstractEntityStateUpdateHandler):
    async def handle(self, state: EntityState, capabilities: list[str]) -> None:
        light = cast(LightState, state)

        onoff_id = self.find_capability(capabilities, "onoff")
        if onoff_id is not None:
            self.handle_on_off(bool(light.state), onoff_id)

        dim_id = self.find_capability(capabilities, "dim")
        if dim_id is not None:
            self.set_capability_value(dim_id, float(light.brightness))

        mode_id = self.find_capability(capabilities, "light_mode")
        if mode_id is not None:
            match light.color_mode:
                case (
                    ColorMode.ON_OFF
                    | ColorMode.UNKNOWN
                    | ColorMode.BRIGHTNESS
                    | ColorMode.LEGACY_BRIGHTNESS
                    | ColorMode.WHITE
                ):
                    pass
                case (
                    ColorMode.RGB
                    | ColorMode.RGB_WHITE
                    | ColorMode.RGB_COLOR_TEMPERATURE
                    | ColorMode.RGB_COLD_WARM_WHITE
                ):
                    self.set_capability_value(mode_id, "color")
                case ColorMode.COLOR_TEMPERATURE | ColorMode.COLD_WARM_WHITE:
                    self.set_capability_value(mode_id, "temperature")
                case _:
                    self.log(f"Unknown LightState.color_mode: {light.color_mode}")

        hue_id = self.find_capability(capabilities, "light_hue")
        sat_id = self.find_capability(capabilities, "light_saturation")
        if hue_id is not None or sat_id is not None:
            hue, saturation, _value = colorsys.rgb_to_hsv(
                float(light.red),
                float(light.green),
                float(light.blue),
            )
            if hue_id is not None:
                self.set_capability_value(hue_id, hue)
            if sat_id is not None:
                self.set_capability_value(sat_id, saturation)

        effect_id = self.find_capability(capabilities, "light_effect")
        if effect_id is not None:
            self.set_capability_value(effect_id, light.effect)

        temp_id = self.find_capability(capabilities, "light_temperature")
        if temp_id is not None and light.color_temperature:
            kelvin = mireds_to_kelvin(light.color_temperature)

            options = self.device.get_capability_options(temp_id)
            min_kelvin = int(options["min_color_temp_kelvin"])
            max_kelvin = int(options["max_color_temp_kelvin"])
            if max_kelvin <= min_kelvin:
                return

            # Homey: 1 = warm (low kelvin), 0 = cool (high kelvin).
            homey_temp = 1 - (kelvin - min_kelvin) / (max_kelvin - min_kelvin)
            self.set_capability_value(
                temp_id,
                max(0.0, min(1.0, homey_temp)),
            )
