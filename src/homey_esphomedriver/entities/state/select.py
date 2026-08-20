"""Push ESPHome SelectState into Homey esphome_select capabilities."""

from __future__ import annotations

from typing import cast

from aioesphomeapi import EntityState, SelectState

from homey_esphomedriver.entities.state.base import (
    AbstractEntityStateUpdateHandler,
)


class SelectEntityStateUpdateHandler(AbstractEntityStateUpdateHandler):
    async def handle(self, state: EntityState, capabilities: list[str]) -> None:
        capability = capabilities[0]
        select = cast(SelectState, state)
        if select.missing_state:
            self.set_capability_value(capability, None)
            return

        self.set_capability_value(capability, str(select.state))
