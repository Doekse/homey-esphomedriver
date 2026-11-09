"""Fan: on/off, speed and preset mode."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from aioesphomeapi import FanInfo

from homey_esphomedriver.system import BoundEntity, SystemCapability


def speed_count(info: FanInfo) -> int:
    """Number of speed steps; Homey ``fan_speed`` moves in steps of ``1 / count``."""
    return info.supported_speed_count or 1


def preset_title(value: str) -> str:
    """Homey enum ids are lowercase; ESPHome presets are titled."""
    return value[:1].upper() + value[1:]


def _report_onoff(state: Any, entity: BoundEntity) -> bool:
    del entity
    return bool(state.state)


def _set_onoff(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts, entity
    return {"state": bool(value)}


def _report_speed(state: Any, entity: BoundEntity) -> float:
    return float(state.speed_level) / speed_count(cast(FanInfo, entity.info))


def _set_speed(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts
    level = round(float(value) * speed_count(cast(FanInfo, entity.info)))
    if level > 0:
        return {"state": True, "speed_level": level}
    return {"state": False}


def _report_mode(state: Any, entity: BoundEntity) -> str | None:
    del entity
    return str(state.preset_mode).lower() or None


def _set_mode(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts, entity
    return {"preset_mode": preset_title(str(value))}


CAPABILITIES: dict[str, SystemCapability] = {
    "onoff": SystemCapability(report_parser=_report_onoff, set_parser=_set_onoff),
    "fan_speed": SystemCapability(report_parser=_report_speed, set_parser=_set_speed),
    "fan_mode": SystemCapability(report_parser=_report_mode, set_parser=_set_mode),
}
