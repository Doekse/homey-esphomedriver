"""Number: any capability reads and writes the entity's value."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homey_esphomedriver.system import BoundEntity, SystemCapability

CAPABILITIES: dict[str, SystemCapability] = {}


def _report(state: Any, entity: BoundEntity) -> float:
    del entity
    return float(state.state)


def _set(value: Any, opts: Mapping[str, Any], entity: BoundEntity) -> dict[str, Any]:
    del opts, entity
    return {"state": float(value)}


def default(capability_id: str) -> SystemCapability:
    del capability_id
    return SystemCapability(report_parser=_report, set_parser=_set)
