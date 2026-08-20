"""Homey heater_operation_mode → ESPHome ``water_heater_command``."""

from __future__ import annotations

from typing import Any

from aioesphomeapi import WaterHeaterMode

from homey_esphomedriver.commands.base import AbstractEntityCommandHandler


class WaterHeaterEntityCommandHandler(AbstractEntityCommandHandler):
    CAPABILITIES = ("heater_operation_mode",)
    ENTITY_TYPE = "water_heater"

    async def heater_operation_mode(
        self,
        value: Any,
        capability_id: str = "heater_operation_mode",
        **_kwargs: Any,
    ) -> None:
        mode = WaterHeaterMode.__members__.get(
            str(value).upper(),
            WaterHeaterMode.OFF,
        )
        self._require_client().command(
            "water_heater_command",
            self._get_entity_key(capability_id),
            mode=int(mode),
        )
