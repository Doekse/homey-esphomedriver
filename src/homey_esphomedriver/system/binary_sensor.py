"""Binary sensor: alarms and other booleans."""

from __future__ import annotations

from typing import Any

from homey_esphomedriver.system import BoundEntity, SystemCapability


def _inverted(state: Any, entity: BoundEntity) -> bool:
    # alarm_connectivity is on when the connection is lost; an ESPHome
    # connectivity sensor is on while connected.
    del entity
    return not state.state


def _charging(state: Any, entity: BoundEntity) -> str:
    del entity
    return "charging" if state.state else "idle"


def _boolean(state: Any, entity: BoundEntity) -> bool:
    del entity
    return bool(state.state)


REPORTS_ONLY = True

CAPABILITIES: dict[str, SystemCapability] = {
    "alarm_connectivity": SystemCapability(report_parser=_inverted),
    "battery_charging_state": SystemCapability(report_parser=_charging),
}


def default(capability_id: str) -> SystemCapability:
    """Any ``alarm_*`` or app capability takes the boolean as is."""
    del capability_id
    return SystemCapability(report_parser=_boolean)
