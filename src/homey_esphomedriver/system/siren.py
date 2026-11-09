"""Siren: on/off and volume. ESPHome does not report a siren's volume."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homey_esphomedriver.system import BoundEntity, SystemCapability


def _report_onoff(state: Any, entity: BoundEntity) -> bool:
    del entity
    return bool(state.state)


def _set_onoff(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts, entity
    return {"state": bool(value)}


def _set_volume(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts, entity
    return {"volume": float(value)}


CAPABILITIES: dict[str, SystemCapability] = {
    "onoff": SystemCapability(report_parser=_report_onoff, set_parser=_set_onoff),
    "volume_set": SystemCapability(set_parser=_set_volume),
}
