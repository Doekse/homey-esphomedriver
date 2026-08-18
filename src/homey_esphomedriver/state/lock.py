"""Push ESPHome LockEntityState into Homey lock capabilities."""

from __future__ import annotations

from typing import cast

from aioesphomeapi import EntityState, LockEntityState, LockState

from homey_esphomedriver.state.base import (
    AbstractEntityStateUpdateHandler,
)


class LockEntityStateUpdateHandler(AbstractEntityStateUpdateHandler):
    async def handle(self, state: EntityState, capabilities: list[str]) -> None:
        lock = cast(LockEntityState, state)

        locked_id = self.find_capability(capabilities, "locked")
        if locked_id is not None:
            self.set_capability_value(locked_id, lock.state == LockState.LOCKED)

        stuck_id = self.find_capability(capabilities, "alarm_stuck")
        if stuck_id is not None:
            self.set_capability_value(stuck_id, lock.state == LockState.JAMMED)
