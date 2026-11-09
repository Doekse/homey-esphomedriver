"""Climate: thermostat mode, temperatures, humidity, fan and swing mode.

Homey temperatures are °C; the entity's own unit comes from its
``temperature_unit``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from aioesphomeapi import (
    ClimateFanMode,
    ClimateInfo,
    ClimateMode,
    ClimateSwingMode,
)

from homey_esphomedriver.system import BoundEntity, SystemCapability
from homey_esphomedriver.units import (
    convert_temperature,
    convert_temperature_from_celsius,
    temperature_unit_label,
)

_THERMOSTAT_MODE = {
    ClimateMode.HEAT: "heat",
    ClimateMode.COOL: "cool",
    ClimateMode.HEAT_COOL: "auto",
    ClimateMode.AUTO: "auto",
    ClimateMode.OFF: "off",
    ClimateMode.DRY: "dry",
    ClimateMode.FAN_ONLY: "fan_only",
}

_SWING_MODE = {
    ClimateSwingMode.BOTH: "both",
    ClimateSwingMode.HORIZONTAL: "horizontal",
    ClimateSwingMode.VERTICAL: "vertical",
}


def on_mode(info: ClimateInfo) -> ClimateMode:
    """Mode that turning the climate on selects: automatic first, then heat or cool."""
    modes = info.supported_modes
    for candidate in (
        ClimateMode.HEAT_COOL,
        ClimateMode.AUTO,
        ClimateMode.HEAT,
        ClimateMode.COOL,
    ):
        if candidate in modes:
            return candidate
    return next((mode for mode in modes if mode != ClimateMode.OFF), ClimateMode.HEAT)


def auto_mode(info: ClimateInfo) -> ClimateMode:
    """Mode behind Homey's ``auto``: heat-cool when supported, else auto."""
    modes = info.supported_modes
    if ClimateMode.HEAT_COOL in modes or ClimateMode.AUTO not in modes:
        return ClimateMode.HEAT_COOL
    return ClimateMode.AUTO


def _unit(entity: BoundEntity) -> str:
    return temperature_unit_label(cast(ClimateInfo, entity.info).temperature_unit)


def _report_onoff(state: Any, entity: BoundEntity) -> bool:
    del entity
    return bool(state.mode != ClimateMode.OFF)


def _set_onoff(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts
    if value:
        return {"mode": on_mode(cast(ClimateInfo, entity.info))}
    return {"mode": ClimateMode.OFF}


def _report_mode(state: Any, entity: BoundEntity) -> str:
    del entity
    return _THERMOSTAT_MODE.get(state.mode, "off")


def _set_mode(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts
    if str(value) == "auto":
        return {"mode": auto_mode(cast(ClimateInfo, entity.info))}
    return {"mode": ClimateMode.__members__.get(str(value).upper(), ClimateMode.OFF)}


def _temperature(field: str) -> SystemCapability:
    """A temperature read from and written to ``field`` of the climate."""

    def report(state: Any, entity: BoundEntity) -> float:
        return convert_temperature(_unit(entity), float(getattr(state, field)))

    def set_value(
        value: Any, opts: Mapping[str, Any], entity: BoundEntity
    ) -> dict[str, Any]:
        del opts
        return {field: convert_temperature_from_celsius(_unit(entity), float(value))}

    return SystemCapability(report_parser=report, set_parser=set_value)


def _report_measure_temperature(state: Any, entity: BoundEntity) -> float:
    return convert_temperature(_unit(entity), float(state.current_temperature))


def _report_humidity(state: Any, entity: BoundEntity) -> float:
    del entity
    return float(state.current_humidity)


def _report_target_humidity(state: Any, entity: BoundEntity) -> float:
    del entity
    return float(state.target_humidity)


def _set_target_humidity(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts, entity
    return {"target_humidity": float(value)}


def _report_fan_mode(state: Any, entity: BoundEntity) -> str | None:
    info = cast(ClimateInfo, entity.info)
    if state.custom_fan_mode:
        value = str(state.custom_fan_mode)
        return value if value in info.supported_custom_fan_modes else None
    if state.fan_mode in info.supported_fan_modes:
        return ClimateFanMode(state.fan_mode).name.lower()
    # A mode the entity does not list is not an option of the Homey picker.
    return None


def _set_fan_mode(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts, entity
    fan_mode = ClimateFanMode.__members__.get(str(value).upper())
    if fan_mode is not None and str(value) == fan_mode.name.lower():
        return {"fan_mode": fan_mode}
    return {"custom_fan_mode": str(value)}


def _report_swing_mode(state: Any, entity: BoundEntity) -> str:
    del entity
    return _SWING_MODE.get(state.swing_mode, "off")


def _set_swing_mode(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts, entity
    for swing_mode, homey in _SWING_MODE.items():
        if str(value) == homey:
            return {"swing_mode": swing_mode}
    return {"swing_mode": ClimateSwingMode.OFF}


CAPABILITIES: dict[str, SystemCapability] = {
    "onoff": SystemCapability(report_parser=_report_onoff, set_parser=_set_onoff),
    "thermostat_mode": SystemCapability(
        report_parser=_report_mode, set_parser=_set_mode
    ),
    "measure_temperature": SystemCapability(report_parser=_report_measure_temperature),
    "target_temperature": _temperature("target_temperature"),
    "target_temperature_min": _temperature("target_temperature_low"),
    "target_temperature_max": _temperature("target_temperature_high"),
    "measure_humidity": SystemCapability(report_parser=_report_humidity),
    "target_humidity": SystemCapability(
        report_parser=_report_target_humidity, set_parser=_set_target_humidity
    ),
    "fan_mode": SystemCapability(
        report_parser=_report_fan_mode, set_parser=_set_fan_mode
    ),
    "swing_mode": SystemCapability(
        report_parser=_report_swing_mode, set_parser=_set_swing_mode
    ),
}
