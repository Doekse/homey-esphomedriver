"""Homey fan / aircleaner capabilities → ESPHome ``fan_command`` / climate fan."""

from __future__ import annotations

from typing import Any

from aioesphomeapi import ClimateFanMode

from homey_esphomedriver.commands.base import AbstractEntityCommandHandler


def _capitalize_preset(value: str) -> str:
    """Homey enum ids are lowercase; ESPHome presets are titled."""
    return value[:1].upper() + value[1:]


class FanEntityCommandHandler(AbstractEntityCommandHandler):
    CAPABILITIES = ("fan_speed", "fan_oscillate", "fan_mode", "aircleaner_mode")
    ENTITY_TYPE = "fan"

    async def fan_speed(
        self,
        value: Any,
        capability_id: str = "fan_speed",
        **_kwargs: Any,
    ) -> None:
        key = self._get_entity_key(capability_id)
        speed = float(value)
        speed_count = int(
            self.device.get_capability_options(capability_id)["speed_count"]
        )
        speed_level = round(speed * speed_count)
        client = self._require_client()
        if speed_level > 0:
            client.command("fan_command", key, state=True, speed_level=speed_level)
        else:
            client.command("fan_command", key, state=False)

    async def fan_oscillate(
        self,
        value: Any,
        capability_id: str = "fan_oscillate",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "fan_command",
            self._get_entity_key(capability_id),
            oscillating=bool(value),
        )

    async def fan_mode(
        self,
        value: Any,
        capability_id: str = "fan_mode",
        **_kwargs: Any,
    ) -> None:
        key = self._get_entity_key(capability_id)
        entity_type = self._get_entity_type(capability_id)
        client = self._require_client()
        if entity_type == "climate":
            fan_mode = ClimateFanMode.__members__.get(str(value).upper())
            if fan_mode is not None and str(value) == fan_mode.name.lower():
                client.command("climate_command", key, fan_mode=fan_mode)
            else:
                client.command("climate_command", key, custom_fan_mode=str(value))
            return
        client.command("fan_command", key, preset_mode=_capitalize_preset(str(value)))

    async def aircleaner_mode(
        self,
        value: Any,
        capability_id: str = "aircleaner_mode",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "fan_command",
            self._get_entity_key(capability_id),
            preset_mode=_capitalize_preset(str(value)),
        )
