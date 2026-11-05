"""Command-handler listener wiring tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from homey_esphomedriver.entities.commands import DeviceEntityCommandHandler
from homey_esphomedriver.entities.commands.generic import (
    WRITABLE_DOMAINS,
    write_entity_value,
)


class _Device:
    def __init__(self, capabilities: list[str]) -> None:
        self._capabilities = list(capabilities)
        self._capabilities_options = {cap: {"key": 1} for cap in capabilities}
        self.single: list[str] = []
        self.multi: list[list[str]] = []

    def get_capabilities(self) -> list[str]:
        return list(self._capabilities)

    def has_capability(self, capability_id: str) -> bool:
        return capability_id in self._capabilities

    def register_capability_listener(
        self, capability_id: str, _listener: object
    ) -> None:
        self.single.append(capability_id)

    def register_multiple_capability_listener(
        self, capability_ids: list[str], _listener: object
    ) -> None:
        self.multi.append(list(capability_ids))


def test_hue_saturation_multi_listener_registers_once_at_init() -> None:
    """Init registers the grouped hue/saturation listener once, not per member."""
    device = _Device(["dim", "light_hue", "light_saturation", "light_mode"])
    DeviceEntityCommandHandler(device).register_listeners()

    assert device.multi == [["light_hue", "light_saturation"]]
    assert "dim" in device.single
    assert "light_mode" in device.single
    assert "light_hue" not in device.single
    assert "light_saturation" not in device.single


def test_hue_saturation_multi_listener_registers_once_when_added() -> None:
    """A refresh batch that adds both members registers the group once."""
    device = _Device(["dim"])
    commands = DeviceEntityCommandHandler(device)
    commands.register_listeners()
    assert device.multi == []

    added = ["light_hue", "light_saturation"]
    device._capabilities.extend(added)
    for capability_id in added:
        commands.register_listener_for_capability(capability_id)
    commands.register_multi_listeners(added)

    assert device.multi == [["light_hue", "light_saturation"]]


def test_each_writable_domain_has_its_own_command() -> None:
    """Writing every entity as a number sends a dropdown a float it rejects."""
    assert {domain: spec.command for domain, spec in WRITABLE_DOMAINS.items()} == {
        "number": "number_command",
        "select": "select_command",
        "switch": "switch_command",
    }
    client = MagicMock()
    write_entity_value(client, "number", 7, "21.5")
    client.command.assert_called_once_with("number_command", 7, 21.5)
