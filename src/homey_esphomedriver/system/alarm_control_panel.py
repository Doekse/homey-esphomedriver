"""Alarm control panel: Homey's home alarm state."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from aioesphomeapi import (
    AlarmControlPanelCommand,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelInfo,
    AlarmControlPanelState,
)

from homey_esphomedriver.system import BoundEntity, SystemCapability

_STATE = {
    AlarmControlPanelState.DISARMED: "disarmed",
    AlarmControlPanelState.ARMED_AWAY: "armed",
    AlarmControlPanelState.ARMED_VACATION: "armed",
    AlarmControlPanelState.ARMED_HOME: "partially_armed",
    AlarmControlPanelState.ARMED_NIGHT: "partially_armed",
    AlarmControlPanelState.ARMED_CUSTOM_BYPASS: "partially_armed",
}
"""Pending, arming, disarming and triggered have no home alarm state."""

_ARMED = (
    (AlarmControlPanelEntityFeature.ARM_AWAY, AlarmControlPanelCommand.ARM_AWAY),
    (
        AlarmControlPanelEntityFeature.ARM_VACATION,
        AlarmControlPanelCommand.ARM_VACATION,
    ),
)
_PARTIALLY_ARMED = (
    (AlarmControlPanelEntityFeature.ARM_HOME, AlarmControlPanelCommand.ARM_HOME),
    (AlarmControlPanelEntityFeature.ARM_NIGHT, AlarmControlPanelCommand.ARM_NIGHT),
    (
        AlarmControlPanelEntityFeature.ARM_CUSTOM_BYPASS,
        AlarmControlPanelCommand.ARM_CUSTOM_BYPASS,
    ),
)


def arm_command(
    info: AlarmControlPanelInfo, homey_state: str
) -> AlarmControlPanelCommand | None:
    """Command for ``armed`` or ``partially_armed``, the first the panel supports."""
    candidates = _ARMED if homey_state == "armed" else _PARTIALLY_ARMED
    for feature, command in candidates:
        if info.supported_features & feature:
            return command
    return None


def _report_state(state: Any, entity: BoundEntity) -> str | None:
    del entity
    return _STATE.get(state.state)


def _set_state(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts
    if value == "disarmed":
        return {"command": AlarmControlPanelCommand.DISARM}
    command = arm_command(cast(AlarmControlPanelInfo, entity.info), str(value))
    if command is None:
        raise ValueError(f"Unsupported homealarm_state: {value}")
    return {"command": command}


CAPABILITIES: dict[str, SystemCapability] = {
    "homealarm_state": SystemCapability(
        report_parser=_report_state, set_parser=_set_state
    ),
}
