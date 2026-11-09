"""Button: any capability presses it; a button reports no state."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homey_esphomedriver.system import BoundEntity, SystemCapability

CAPABILITIES: dict[str, SystemCapability] = {}


def _press(value: Any, opts: Mapping[str, Any], entity: BoundEntity) -> dict[str, Any]:
    del value, opts, entity
    return {}


def default(capability_id: str) -> SystemCapability:
    del capability_id
    return SystemCapability(set_parser=_press)
