"""Push ESPHome TextSensorState into Homey string capabilities."""

from __future__ import annotations

from typing import cast

from aioesphomeapi import EntityState, TextSensorState

from homey_esphomedriver.entities.state.base import (
    AbstractEntityStateUpdateHandler,
)
from homey_esphomedriver.esphome_util import format_date, format_timestamp


class TextSensorEntityStateUpdateHandler(AbstractEntityStateUpdateHandler):
    async def handle(self, state: EntityState, capabilities: list[str]) -> None:
        capability = capabilities[0]
        text = cast(TextSensorState, state)
        if text.missing_state:
            self.set_capability_value(capability, None)
            return

        value = str(text.state)
        if capability.startswith("measure_date"):
            value = format_date(value)
        elif capability.startswith("measure_timestamp"):
            value = format_timestamp(value)

        self.set_capability_value(capability, value)
