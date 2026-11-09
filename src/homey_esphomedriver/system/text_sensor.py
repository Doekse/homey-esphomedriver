"""Text sensor: any capability takes the text."""

from __future__ import annotations

from typing import Any

from homey_esphomedriver.system import BoundEntity, SystemCapability

REPORTS_ONLY = True

CAPABILITIES: dict[str, SystemCapability] = {}


def _text(state: Any, entity: BoundEntity) -> str:
    del entity
    return str(state.state)


def default(capability_id: str) -> SystemCapability:
    del capability_id
    return SystemCapability(report_parser=_text)
