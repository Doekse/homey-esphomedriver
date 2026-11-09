"""Cover: window coverings and garage doors. Position and tilt are 0–1 in both."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aioesphomeapi import CoverOperation

from homey_esphomedriver.system import BoundEntity, SystemCapability

_OPERATION = {
    CoverOperation.IS_OPENING: "up",
    CoverOperation.IS_CLOSING: "down",
    CoverOperation.IDLE: "idle",
}


def _report_state(state: Any, entity: BoundEntity) -> str | None:
    del entity
    return _OPERATION.get(state.current_operation)


def _set_state(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts, entity
    if value == "up":
        return {"position": 1.0}
    if value == "down":
        return {"position": 0.0}
    return {"stop": True}


def _report_position(state: Any, entity: BoundEntity) -> float:
    del entity
    return float(state.position)


def _set_position(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts, entity
    return {"position": float(value)}


def _report_tilt(state: Any, entity: BoundEntity) -> float:
    del entity
    return float(state.tilt)


def _set_tilt(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts, entity
    return {"tilt": float(value)}


def _tilt_to(tilt: float) -> SystemCapability:
    def set_tilt(
        value: Any, opts: Mapping[str, Any], entity: BoundEntity
    ) -> dict[str, Any]:
        del value, opts, entity
        return {"tilt": tilt}

    return SystemCapability(set_parser=set_tilt)


def _report_closed(state: Any, entity: BoundEntity) -> bool | None:
    del entity
    # Only a cover that stopped moving is open or closed.
    if state.current_operation != CoverOperation.IDLE:
        return None
    return bool(state.position == 0.0)


def _set_closed(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts, entity
    return {"position": 0.0 if value else 1.0}


CAPABILITIES: dict[str, SystemCapability] = {
    "windowcoverings_state": SystemCapability(
        report_parser=_report_state, set_parser=_set_state
    ),
    "windowcoverings_set": SystemCapability(
        report_parser=_report_position, set_parser=_set_position
    ),
    "windowcoverings_tilt_set": SystemCapability(
        report_parser=_report_tilt, set_parser=_set_tilt
    ),
    "windowcoverings_tilt_up": _tilt_to(1.0),
    "windowcoverings_tilt_down": _tilt_to(0.0),
    "windowcoverings_closed": SystemCapability(
        report_parser=_report_closed, set_parser=_set_closed
    ),
    "garagedoor_closed": SystemCapability(
        report_parser=_report_closed, set_parser=_set_closed
    ),
}
