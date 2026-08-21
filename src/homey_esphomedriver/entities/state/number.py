"""Push ESPHome NumberState into Homey esphome_number capabilities."""

from __future__ import annotations

import math
from typing import cast

from aioesphomeapi import EntityState, NumberState

from homey_esphomedriver.entities.state.base import (
    AbstractEntityStateUpdateHandler,
)


class NumberEntityStateUpdateHandler(AbstractEntityStateUpdateHandler):
    async def handle(self, state: EntityState, capabilities: list[str]) -> None:
        capability = capabilities[0]
        number = cast(NumberState, state)
        if number.missing_state or _is_missing_number(number.state):
            self.set_capability_value(capability, None)
            return

        self.set_capability_value(capability, float(number.state))


def _is_missing_number(value: float) -> bool:
    """ESPHome may leave NaN when a value is not yet available."""
    return math.isnan(value)
