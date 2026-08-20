"""Homey climate capabilities → ESPHome ``climate_command`` / water heater."""

from __future__ import annotations

from typing import Any

from aioesphomeapi import ClimateMode, ClimatePreset, ClimateSwingMode

from homey_esphomedriver.commands.base import AbstractEntityCommandHandler
from homey_esphomedriver.units import convert_temperature_from_celsius


class ClimateEntityCommandHandler(AbstractEntityCommandHandler):
    CAPABILITIES = (
        "thermostat_mode",
        "thermostat_preset",
        "target_temperature",
        "target_temperature_min",
        "target_temperature_max",
        "target_humidity",
        "swing_mode",
    )
    ENTITY_TYPE = "climate"

    def _entity_temperature(self, capability_id: str, value: Any) -> float:
        """Convert Homey °C to the entity's configured temperature unit."""
        unit = str(self.device.get_capability_options(capability_id)["esphome_unit"])
        return convert_temperature_from_celsius(unit, float(value))

    def _set_target_temperature(
        self, capability_id: str, value: Any, field: str
    ) -> None:
        key = self._get_entity_key(capability_id)
        command = (
            "water_heater_command"
            if self._get_entity_type(capability_id) == "water_heater"
            else "climate_command"
        )
        self._require_client().command(
            command, key, **{field: self._entity_temperature(capability_id, value)}
        )

    async def thermostat_mode(
        self,
        value: Any,
        capability_id: str = "thermostat_mode",
        **_kwargs: Any,
    ) -> None:
        if str(value) == "auto":
            mode = ClimateMode(
                int(
                    self.device.get_capability_options(capability_id).get(
                        "climate_auto_mode",
                        int(ClimateMode.HEAT_COOL),
                    )
                )
            )
        else:
            mode = ClimateMode.__members__.get(str(value).upper(), ClimateMode.OFF)
        self._require_client().command(
            "climate_command",
            self._get_entity_key(capability_id),
            mode=mode,
        )

    async def thermostat_preset(
        self,
        value: Any,
        capability_id: str = "thermostat_preset",
        **_kwargs: Any,
    ) -> None:
        key = self._get_entity_key(capability_id)
        client = self._require_client()
        preset = ClimatePreset.__members__.get(str(value).upper())
        if preset is not None and str(value) == preset.name.lower():
            client.command("climate_command", key, preset=preset)
            return
        client.command("climate_command", key, custom_preset=str(value))

    async def target_temperature(
        self,
        value: Any,
        capability_id: str = "target_temperature",
        **_kwargs: Any,
    ) -> None:
        self._set_target_temperature(capability_id, value, "target_temperature")

    async def target_temperature_min(
        self,
        value: Any,
        capability_id: str = "target_temperature_min",
        **_kwargs: Any,
    ) -> None:
        self._set_target_temperature(capability_id, value, "target_temperature_low")

    async def target_temperature_max(
        self,
        value: Any,
        capability_id: str = "target_temperature_max",
        **_kwargs: Any,
    ) -> None:
        self._set_target_temperature(capability_id, value, "target_temperature_high")

    async def target_humidity(
        self,
        value: Any,
        capability_id: str = "target_humidity",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "climate_command",
            self._get_entity_key(capability_id),
            target_humidity=float(value),
        )

    async def swing_mode(
        self,
        value: Any,
        capability_id: str = "swing_mode",
        **_kwargs: Any,
    ) -> None:
        match str(value):
            case "both":
                swing_mode = ClimateSwingMode.BOTH
            case "horizontal":
                swing_mode = ClimateSwingMode.HORIZONTAL
            case "vertical":
                swing_mode = ClimateSwingMode.VERTICAL
            case _:
                swing_mode = ClimateSwingMode.OFF
        self._require_client().command(
            "climate_command",
            self._get_entity_key(capability_id),
            swing_mode=swing_mode,
        )
