"""Push ESPHome AlarmControlPanelEntityState into Homey homealarm capabilities."""

from __future__ import annotations

from typing import cast

from aioesphomeapi import (
    AlarmControlPanelEntityState,
    AlarmControlPanelState,
    EntityState,
)

from homey_esphomedriver.state.base import (
    AbstractEntityStateUpdateHandler,
)


class AlarmControlPanelEntityStateUpdateHandler(AbstractEntityStateUpdateHandler):
    async def handle(self, state: EntityState, capabilities: list[str]) -> None:
        panel = cast(AlarmControlPanelEntityState, state)

        new_state: str | None = None
        match panel.state:
            case AlarmControlPanelState.DISARMED:
                new_state = "disarmed"
            case (
                AlarmControlPanelState.ARMED_AWAY
                | AlarmControlPanelState.ARMED_VACATION
            ):
                new_state = "armed"
            case (
                AlarmControlPanelState.ARMED_HOME
                | AlarmControlPanelState.ARMED_NIGHT
                | AlarmControlPanelState.ARMED_CUSTOM_BYPASS
            ):
                new_state = "partially_armed"
            case (
                AlarmControlPanelState.PENDING
                | AlarmControlPanelState.ARMING
                | AlarmControlPanelState.DISARMING
                | AlarmControlPanelState.TRIGGERED
            ):
                # Homey homealarm_state has no pending/arming/disarming.
                # TRIGGERED uses alarm_triggered.
                pass

        homealarm_id = self.find_capability(capabilities, "homealarm_state")
        if new_state is not None and homealarm_id is not None:
            self.set_capability_value(homealarm_id, new_state)

        triggered_id = self.find_capability(capabilities, "alarm_triggered")
        if triggered_id is not None:
            self.set_capability_value(
                triggered_id,
                panel.state == AlarmControlPanelState.TRIGGERED,
            )
