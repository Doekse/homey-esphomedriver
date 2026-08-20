"""Homey light capabilities → ESPHome ``light_command``."""

from __future__ import annotations

import colorsys
from collections.abc import Mapping
from typing import Any

from aioesphomeapi import ColorMode

from homey_esphomedriver.commands.base import AbstractEntityCommandHandler
from homey_esphomedriver.units import kelvin_to_mireds


class LightEntityCommandHandler(AbstractEntityCommandHandler):
    CAPABILITIES = ("dim", "light_mode", "light_temperature", "light_effect")
    MULTI_CAPABILITIES = ((("light_hue", "light_saturation"), "light_hue_saturation"),)
    ENTITY_TYPE = "light"

    async def dim(
        self,
        value: Any,
        capability_id: str = "dim",
        **_kwargs: Any,
    ) -> None:
        key = self._get_entity_key(capability_id)
        client = self._require_client()
        brightness = float(value)
        if brightness > 0:
            client.command("light_command", key, state=True, brightness=brightness)
        else:
            client.command("light_command", key, state=False)

    async def light_mode(
        self,
        value: Any,
        **_kwargs: Any,
    ) -> None:
        if value == "color":
            if self.device.has_capability("light_hue"):
                await self.device.trigger_capability_listener(
                    "light_hue",
                    self.device.get_capability_value("light_hue"),
                )
        elif value == "temperature":
            if self.device.has_capability("light_temperature"):
                await self.device.trigger_capability_listener(
                    "light_temperature",
                    self.device.get_capability_value("light_temperature"),
                )

    async def light_effect(
        self,
        value: Any,
        capability_id: str = "light_effect",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "light_command",
            self._get_entity_key(capability_id),
            state=True,
            effect=str(value),
        )

    async def light_temperature(
        self,
        value: Any,
        capability_id: str = "light_temperature",
        **_kwargs: Any,
    ) -> None:
        if self.device.has_capability("light_mode"):
            await self.device.set_capability_value("light_mode", "temperature")

        options = self.device.get_capability_options(capability_id)
        min_kelvin = int(options["min_color_temp_kelvin"])
        max_kelvin = int(options["max_color_temp_kelvin"])
        kelvin = min_kelvin + (1 - float(value)) * (max_kelvin - min_kelvin)
        if kelvin <= 0:
            raise ValueError("Invalid color temperature")

        self._require_client().command(
            "light_command",
            self._get_entity_key(capability_id),
            state=True,
            color_mode=int(ColorMode.COLOR_TEMPERATURE),
            color_temperature=kelvin_to_mireds(kelvin),
        )

    async def light_hue_saturation(
        self,
        values: Mapping[str, Any],
        **_kwargs: Any,
    ) -> None:
        # The listener runs before Homey commits capability state; read from values.
        hue = (
            values["light_hue"]
            if "light_hue" in values
            else self.device.get_capability_value("light_hue")
        )
        sat = (
            values["light_saturation"]
            if "light_saturation" in values
            else self.device.get_capability_value("light_saturation")
        )

        if self.device.has_capability("light_mode"):
            await self.device.set_capability_value("light_mode", "color")

        red, green, blue = colorsys.hsv_to_rgb(
            float(hue) if hue is not None else 0.0,
            float(sat) if sat is not None else 0.0,
            1.0,
        )
        self._require_client().command(
            "light_command",
            self._get_entity_key("light_hue"),
            state=True,
            color_mode=int(ColorMode.RGB),
            color_brightness=1.0,
            rgb=(red, green, blue),
        )
