"""Push ESPHome CoverState into Homey windowcovering capabilities."""

from __future__ import annotations

from typing import cast

from aioesphomeapi import CoverOperation, CoverState, EntityState

from homey_esphomedriver.entities.state.base import (
    AbstractEntityStateUpdateHandler,
)


class CoverEntityStateUpdateHandler(AbstractEntityStateUpdateHandler):
    async def handle(self, state: EntityState, capabilities: list[str]) -> None:
        cover = cast(CoverState, state)

        state_id = self.find_capability(capabilities, "windowcoverings_state")
        match cover.current_operation:
            case CoverOperation.IS_OPENING:
                if state_id is not None:
                    self.set_capability_value(state_id, "up")
            case CoverOperation.IS_CLOSING:
                if state_id is not None:
                    self.set_capability_value(state_id, "down")
            case CoverOperation.IDLE:
                if state_id is not None:
                    self.set_capability_value(state_id, "idle")
                closed_id = self.find_capability(capabilities, "garagedoor_closed")
                if closed_id is not None:
                    self.set_capability_value(closed_id, cover.position == 0.0)
            case _:
                self.error(f"Unknown CoverOperation: {cover.current_operation}")

        set_id = self.find_capability(capabilities, "windowcoverings_set")
        if set_id is not None:
            self.set_capability_value(set_id, float(cover.position))

        tilt_id = self.find_capability(capabilities, "windowcoverings_tilt_set")
        if tilt_id is not None:
            self.set_capability_value(tilt_id, float(cover.tilt))
