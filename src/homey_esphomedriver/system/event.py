"""Event: any capability takes the event type that fired.

Events have no Homey system capability. An app usually listens with
``register_state_listener`` and fires its own Flow trigger instead.
"""

from __future__ import annotations

from typing import Any

from homey_esphomedriver.system import BoundEntity, SystemCapability

REPORTS_ONLY = True

CAPABILITIES: dict[str, SystemCapability] = {}


def _event_type(state: Any, entity: BoundEntity) -> str:
    del entity
    return str(state.event_type)


def default(capability_id: str) -> SystemCapability:
    del capability_id
    return SystemCapability(report_parser=_event_type)
