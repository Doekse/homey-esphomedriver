"""Homey homealarm_state → ESPHome ``alarm_control_panel_command``."""

from __future__ import annotations

from typing import Any

from aioesphomeapi import AlarmControlPanelCommand

from homey_esphomedriver.commands.base import AbstractEntityCommandHandler


class AlarmControlPanelEntityCommandHandler(AbstractEntityCommandHandler):
    CAPABILITIES = ("homealarm_state",)
    ENTITY_TYPE = "alarm_control_panel"

    async def homealarm_state(
        self,
        value: Any,
        capability_id: str = "homealarm_state",
        **_kwargs: Any,
    ) -> None:
        options = self.device.get_capability_options(capability_id)

        if value == "disarmed":
            command = AlarmControlPanelCommand.DISARM
        elif value == "armed":
            command = AlarmControlPanelCommand(int(options["alarm_armed_command"]))
        elif value == "partially_armed":
            command = AlarmControlPanelCommand(int(options["alarm_partial_command"]))
        else:
            self.device.error("Invalid homealarm_state", value)
            return

        self._require_client().command(
            "alarm_control_panel_command",
            self._get_entity_key(capability_id),
            command,
        )
