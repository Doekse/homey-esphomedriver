"""Multi-domain onoff plus button / number / select command handlers."""

from __future__ import annotations

from typing import Any

from aioesphomeapi import ClimateMode

from homey_esphomedriver.commands.base import AbstractEntityCommandHandler


class GenericCommandHandler(AbstractEntityCommandHandler):
    CAPABILITIES = ("onoff", "button", "number", "select")

    async def onoff(
        self,
        value: Any,
        capability_id: str = "onoff",
        **_kwargs: Any,
    ) -> None:
        key = self._get_entity_key(capability_id)
        entity_type = self._get_entity_type(capability_id)
        client = self._require_client()

        if entity_type == "light":
            client.command("light_command", key, state=bool(value))
            return
        if entity_type == "fan":
            client.command("fan_command", key, state=bool(value))
            return
        if entity_type == "valve":
            client.command("valve_command", key, position=1.0 if value else 0.0)
            return
        if entity_type == "climate":
            if value:
                client.command(
                    "climate_command",
                    key,
                    mode=ClimateMode(
                        int(
                            self.device.get_capability_options(capability_id)[
                                "climate_on_mode"
                            ]
                        )
                    ),
                )
            else:
                client.command("climate_command", key, mode=ClimateMode.OFF)
            return
        if entity_type == "water_heater":
            client.command("water_heater_command", key, on=bool(value))
            return
        if entity_type == "siren":
            client.command("siren_command", key, state=bool(value))
            return
        if entity_type == "switch":
            client.command("switch_command", key, bool(value))
            return

        raise ValueError(f"Unsupported entity type for onoff: {entity_type}")

    async def button(self, *, capability_id: str, **_kwargs: Any) -> None:
        self._require_client().command(
            "button_command", self._get_entity_key(capability_id)
        )

    async def number(
        self,
        value: Any,
        *,
        capability_id: str,
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "number_command",
            self._get_entity_key(capability_id),
            float(value),
        )

    async def select(
        self,
        value: Any,
        *,
        capability_id: str,
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "select_command",
            self._get_entity_key(capability_id),
            str(value),
        )
