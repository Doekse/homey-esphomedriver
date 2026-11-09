"""Water heater: on/off, operation mode and temperatures in °C."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from aioesphomeapi import WaterHeaterInfo, WaterHeaterMode, WaterHeaterStateFlag

from homey_esphomedriver.system import BoundEntity, SystemCapability
from homey_esphomedriver.units import (
    convert_temperature,
    convert_temperature_from_celsius,
    temperature_unit_label,
)

_MODE = {
    WaterHeaterMode.OFF: "off",
    WaterHeaterMode.ECO: "eco",
    WaterHeaterMode.ELECTRIC: "electric",
    WaterHeaterMode.PERFORMANCE: "performance",
    WaterHeaterMode.HIGH_DEMAND: "high_demand",
    WaterHeaterMode.HEAT_PUMP: "heat_pump",
    WaterHeaterMode.GAS: "gas",
}


def _unit(entity: BoundEntity) -> str:
    return temperature_unit_label(cast(WaterHeaterInfo, entity.info).temperature_unit)


def _report_onoff(state: Any, entity: BoundEntity) -> bool:
    del entity
    return bool(state.state & WaterHeaterStateFlag.ON)


def _set_onoff(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts, entity
    return {"on": bool(value)}


def _report_mode(state: Any, entity: BoundEntity) -> str | None:
    del entity
    if state.mode is None:
        return None
    return _MODE.get(state.mode, "off")


def _set_mode(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts, entity
    mode = WaterHeaterMode.__members__.get(str(value).upper(), WaterHeaterMode.OFF)
    return {"mode": int(mode)}


def _temperature(field: str, *, settable: bool = True) -> SystemCapability:
    """A temperature read from and written to ``field`` of the water heater."""

    def report(state: Any, entity: BoundEntity) -> float:
        return convert_temperature(_unit(entity), float(getattr(state, field)))

    def set_value(
        value: Any, opts: Mapping[str, Any], entity: BoundEntity
    ) -> dict[str, Any]:
        del opts
        return {field: convert_temperature_from_celsius(_unit(entity), float(value))}

    return SystemCapability(
        report_parser=report, set_parser=set_value if settable else None
    )


CAPABILITIES: dict[str, SystemCapability] = {
    "onoff": SystemCapability(report_parser=_report_onoff, set_parser=_set_onoff),
    "heater_operation_mode": SystemCapability(
        report_parser=_report_mode, set_parser=_set_mode
    ),
    "measure_temperature": _temperature("current_temperature", settable=False),
    "target_temperature": _temperature("target_temperature"),
    "target_temperature_min": _temperature("target_temperature_low"),
    "target_temperature_max": _temperature("target_temperature_high"),
}
