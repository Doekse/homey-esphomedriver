"""Lock: locked state and jams."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aioesphomeapi import LockCommand, LockState

from homey_esphomedriver.system import BoundEntity, SystemCapability


def _report_locked(state: Any, entity: BoundEntity) -> bool:
    del entity
    return bool(state.state == LockState.LOCKED)


def _set_locked(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts, entity
    return {"command": LockCommand.LOCK if value else LockCommand.UNLOCK}


def _report_jammed(state: Any, entity: BoundEntity) -> bool:
    del entity
    return bool(state.state == LockState.JAMMED)


CAPABILITIES: dict[str, SystemCapability] = {
    "locked": SystemCapability(report_parser=_report_locked, set_parser=_set_locked),
    "alarm_door_fault": SystemCapability(report_parser=_report_jammed),
}
