"""Light: on/off, dim, color and color temperature.

ESPHome brightness and RGB are 0–1 and color temperature is mireds. Homey
``dim``, ``light_hue`` and ``light_saturation`` are 0–1, and
``light_temperature`` runs from 0 (cool) to 1 (warm) across the light's range.
"""

from __future__ import annotations

import colorsys
from collections.abc import Mapping
from typing import Any, cast

from aioesphomeapi import ColorMode, LightInfo

from homey_esphomedriver.system import BoundEntity, MultiCapability, SystemCapability
from homey_esphomedriver.units import kelvin_to_mireds, mireds_to_kelvin

_DEFAULT_MIN_KELVIN = 2000
_DEFAULT_MAX_KELVIN = 6500

_COLOR_MODES = frozenset(
    {
        ColorMode.RGB,
        ColorMode.RGB_WHITE,
        ColorMode.RGB_COLOR_TEMPERATURE,
        ColorMode.RGB_COLD_WARM_WHITE,
    }
)
_TEMPERATURE_MODES = frozenset({ColorMode.COLOR_TEMPERATURE, ColorMode.COLD_WARM_WHITE})


def kelvin_range(info: LightInfo) -> tuple[int, int]:
    """Warmest and coolest color temperature the light supports, in kelvin."""
    warmest = (
        int(round(mireds_to_kelvin(info.max_mireds)))
        if info.max_mireds
        else _DEFAULT_MIN_KELVIN
    )
    coolest = (
        int(round(mireds_to_kelvin(info.min_mireds)))
        if info.min_mireds
        else _DEFAULT_MAX_KELVIN
    )
    return warmest, coolest


def _report_onoff(state: Any, entity: BoundEntity) -> bool:
    del entity
    return bool(state.state)


def _set_onoff(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts, entity
    return {"state": bool(value)}


def _report_dim(state: Any, entity: BoundEntity) -> float:
    del entity
    return float(state.brightness)


def _set_dim(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts, entity
    brightness = float(value)
    if brightness > 0:
        return {"state": True, "brightness": brightness}
    return {"state": False}


def _report_mode(state: Any, entity: BoundEntity) -> str | None:
    del entity
    if state.color_mode in _COLOR_MODES:
        return "color"
    if state.color_mode in _TEMPERATURE_MODES:
        return "temperature"
    # On/off, brightness and white modes have no Homey light mode.
    return None


def _set_mode(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any] | None:
    """Switch to the color or temperature the other capabilities hold."""
    del opts
    if value == "color":
        return _color_command(
            entity.capability_value("light_hue"),
            entity.capability_value("light_saturation"),
        )
    if value == "temperature":
        temperature = entity.capability_value("light_temperature")
        if temperature is None:
            return None
        return _temperature_command(float(temperature), entity)
    return None


def _report_hue(state: Any, entity: BoundEntity) -> float:
    del entity
    return _hsv(state)[0]


def _report_saturation(state: Any, entity: BoundEntity) -> float:
    del entity
    return _hsv(state)[1]


def _hsv(state: Any) -> tuple[float, float, float]:
    return colorsys.rgb_to_hsv(float(state.red), float(state.green), float(state.blue))


def _set_hue_saturation(
    values: Mapping[str, Any], opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    # The listener runs before Homey commits the values, so an unchanged one
    # comes from the device.
    del opts
    hue = values.get("light_hue", entity.capability_value("light_hue"))
    saturation = values.get(
        "light_saturation", entity.capability_value("light_saturation")
    )
    return _color_command(hue, saturation)


def _color_command(hue: Any, saturation: Any) -> dict[str, Any]:
    red, green, blue = colorsys.hsv_to_rgb(
        float(hue) if hue is not None else 0.0,
        float(saturation) if saturation is not None else 0.0,
        1.0,
    )
    return {
        "state": True,
        "color_mode": int(ColorMode.RGB),
        "color_brightness": 1.0,
        "rgb": (red, green, blue),
    }


def _report_temperature(state: Any, entity: BoundEntity) -> float | None:
    if not state.color_temperature:
        return None
    warmest, coolest = kelvin_range(cast(LightInfo, entity.info))
    if coolest <= warmest:
        return None
    kelvin = mireds_to_kelvin(state.color_temperature)
    # Homey: 1 is warm (low kelvin), 0 is cool (high kelvin).
    value = 1 - (kelvin - warmest) / (coolest - warmest)
    return max(0.0, min(1.0, value))


def _set_temperature(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts
    return _temperature_command(float(value), entity)


def _temperature_command(value: float, entity: BoundEntity) -> dict[str, Any]:
    warmest, coolest = kelvin_range(cast(LightInfo, entity.info))
    kelvin = warmest + (1 - value) * (coolest - warmest)
    if kelvin <= 0:
        raise ValueError("Invalid color temperature")
    return {
        "state": True,
        "color_mode": int(ColorMode.COLOR_TEMPERATURE),
        "color_temperature": kelvin_to_mireds(kelvin),
    }


CAPABILITIES: dict[str, SystemCapability] = {
    "onoff": SystemCapability(report_parser=_report_onoff, set_parser=_set_onoff),
    "dim": SystemCapability(report_parser=_report_dim, set_parser=_set_dim),
    "light_mode": SystemCapability(report_parser=_report_mode, set_parser=_set_mode),
    "light_hue": SystemCapability(report_parser=_report_hue),
    "light_saturation": SystemCapability(report_parser=_report_saturation),
    "light_temperature": SystemCapability(
        report_parser=_report_temperature, set_parser=_set_temperature
    ),
}

MULTI = (
    MultiCapability(
        capabilities=("light_hue", "light_saturation"),
        set_parser=_set_hue_saturation,
    ),
)
