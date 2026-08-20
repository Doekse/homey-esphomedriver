"""Pure helpers for settings-page fields backed by an ESPHome entity.

Kept out of :mod:`esphome_device` so they can be imported and tested without
the Homey runtime, the same way :mod:`refresh` and :mod:`units` are.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aioesphomeapi import NumberInfo, SelectInfo, SwitchInfo


def setting_bool(value: Any) -> bool:
    """Read a Homey checkbox setting, whose stored form may be a string."""
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in {"true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off", ""}:
        return False
    msg = f"Cannot read {value!r} as a boolean"
    raise ValueError(msg)


def setting_matches(wanted: Any, reported: Any) -> bool:
    """Whether the node already holds the value Homey wants.

    Numbers compare with a tolerance, because a float that round-trips through
    Homey can differ in the last bit without being a different value. A mapped
    dropdown or switch reports text or a bool, so those compare by their
    normalised form rather than being forced through ``float``.
    """
    try:
        return abs(float(wanted) - float(reported)) < 1e-6
    except TypeError, ValueError:
        pass
    if isinstance(wanted, bool) or isinstance(reported, bool):
        try:
            return setting_bool(wanted) is setting_bool(reported)
        except ValueError:
            return False
    return str(wanted).strip() == str(reported).strip()


SETTING_COMMANDS: dict[type, tuple[str, Callable[[Any], Any]]] = {
    NumberInfo: ("number_command", float),
    SelectInfo: ("select_command", str),
    SwitchInfo: ("switch_command", setting_bool),
}
"""Native API command per mapped-entity type, with the state each one takes.

A `settingEntities` mapping names an object id, so the entity type is whatever
the YAML author chose; writing every one of them as a number sends a dropdown
a float it rejects and a switch a value it ignores.
"""
