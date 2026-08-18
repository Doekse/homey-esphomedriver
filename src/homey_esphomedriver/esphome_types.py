"""Shared typing for ESPHome Homey device objects built at pair time."""

from __future__ import annotations

from typing import Any, NotRequired, Required, TypedDict

HomeyEspHomeDeviceOption = TypedDict(
    "HomeyEspHomeDeviceOption",
    {
        "name": Required[str],
        "data": Required[dict[str, Any]],
        "store": Required[dict[str, Any]],
        "settings": Required[dict[str, bool | float | str | None]],
        "capabilities": Required[list[str]],
        "capabilitiesOptions": Required[dict[str, dict[str, Any]]],
        "class": NotRequired[str],
        "icon": NotRequired[str],
    },
)
HomeyEspHomeDeviceOption.__doc__ = (
    "Pair-time payload passed to Homey's ``createDevice``."
)
