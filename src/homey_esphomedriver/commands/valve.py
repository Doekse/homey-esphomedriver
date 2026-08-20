"""Homey valve position → ESPHome ``valve_command``."""

from __future__ import annotations

from typing import Any

from homey_esphomedriver.commands.base import AbstractEntityCommandHandler


class ValveEntityCommandHandler(AbstractEntityCommandHandler):
    CAPABILITIES = ("valve_position",)
    ENTITY_TYPE = "valve"

    async def valve_position(
        self,
        value: Any,
        capability_id: str = "valve_position",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "valve_command",
            self._get_entity_key(capability_id),
            position=float(value),
        )
