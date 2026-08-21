"""Push ESPHome SwitchState into Homey onoff capabilities."""

from __future__ import annotations

from typing import cast

from aioesphomeapi import EntityState, SwitchState

from homey_esphomedriver.entities.state.base import (
    AbstractEntityStateUpdateHandler,
)


class SwitchEntityStateUpdateHandler(AbstractEntityStateUpdateHandler):
    async def handle(self, state: EntityState, capabilities: list[str]) -> None:
        switch = cast(SwitchState, state)
        for capability in capabilities:
            self.handle_on_off(bool(switch.state), capability)
