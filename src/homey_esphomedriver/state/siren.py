"""Push ESPHome SirenState into Homey onoff capabilities.

Volume is command-only; ESPHome does not report siren volume in state.
"""

from __future__ import annotations

from typing import cast

from aioesphomeapi import EntityState, SirenState

from homey_esphomedriver.state.base import (
    AbstractEntityStateUpdateHandler,
)


class SirenEntityStateUpdateHandler(AbstractEntityStateUpdateHandler):
    async def handle(self, state: EntityState, capabilities: list[str]) -> None:
        siren = cast(SirenState, state)
        onoff_id = self.find_capability(capabilities, "onoff")
        if onoff_id is not None:
            self.handle_on_off(bool(siren.state), onoff_id)
