"""Valve: open/closed and position. Position is 0–1 in both."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homey_esphomedriver.system import BoundEntity, SystemCapability


def _report_onoff(state: Any, entity: BoundEntity) -> bool:
    del entity
    # Homey onoff is open; ESPHome position 0.0 is closed.
    return bool(state.position != 0.0)


def _set_onoff(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts, entity
    return {"position": 1.0 if value else 0.0}


def _report_position(state: Any, entity: BoundEntity) -> float:
    del entity
    return float(state.position)


def _set_position(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts, entity
    return {"position": float(value)}


CAPABILITIES: dict[str, SystemCapability] = {
    "onoff": SystemCapability(report_parser=_report_onoff, set_parser=_set_onoff),
    "valve_position": SystemCapability(
        report_parser=_report_position, set_parser=_set_position
    ),
}
