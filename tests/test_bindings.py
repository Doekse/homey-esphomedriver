"""Binding capabilities and listeners to ESPHome entities.

An app declares its capabilities in compose and binds each one in
``on_esphome_init``; the system capabilities supply the parsers. These tests
pin registration, how states and commands flow, and how the bindings follow
the entities of each connection.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from aioesphomeapi import (
    LightInfo,
    LightState,
    NumberInfo,
    NumberState,
    SensorInfo,
    SensorState,
    SwitchInfo,
    SwitchState,
)

from homey_esphomedriver.bindings import CapabilityBindings

RELAY = SwitchInfo(object_id="relay", key=1, name="Relay")
LED = LightInfo(object_id="led", key=2, name="Status LED")
LEVEL = NumberInfo(object_id="level", key=3, name="LED level")
TEMPERATURE = SensorInfo(
    object_id="temperature", key=4, name="Temperature", unit_of_measurement="°F"
)


class _Device:
    """The few Homey device calls the bindings make."""

    def __init__(self, capabilities: list[str], *, available: bool = True) -> None:
        self.capabilities = capabilities
        self.values: dict[str, Any] = {}
        self.written: list[tuple[str, Any]] = []
        self._capability_listeners: dict[str, Callable[..., Any]] = {}
        self.multi: list[tuple[list[str], Callable[..., Any]]] = []
        self.client = SimpleNamespace(command=MagicMock())
        self.available = available
        self.error = MagicMock()
        self.log = MagicMock()
        self.homey = SimpleNamespace(
            translate=lambda key, **tags: f"{key}:{','.join(tags.values())}"
        )

    def has_capability(self, capability_id: str) -> bool:
        return capability_id in self.capabilities

    def get_capability_value(self, capability_id: str) -> Any:
        return self.values.get(capability_id)

    async def set_capability_value(self, capability_id: str, value: Any) -> None:
        self.values[capability_id] = value
        self.written.append((capability_id, value))

    def register_capability_listener(
        self, capability_id: str, listener: Callable[..., Any]
    ) -> None:
        self._capability_listeners[capability_id] = listener

    def register_multiple_capability_listener(
        self, capability_ids: list[str], listener: Callable[..., Any]
    ) -> None:
        self.multi.append((capability_ids, listener))
        for capability_id in capability_ids:
            self._capability_listeners[capability_id] = listener

    def _require_client(self) -> Any:
        if not self.available:
            raise RuntimeError("errors.device_not_connected")
        return self.client


def _bindings(*capabilities: str) -> tuple[_Device, CapabilityBindings]:
    device = _Device(list(capabilities))
    return device, CapabilityBindings(device)  # type: ignore[arg-type]


async def _settle() -> None:
    for _ in range(3):
        await asyncio.sleep(0)


# --- registration -----------------------------------------------------------


def test_capability_the_device_lacks_is_rejected() -> None:
    _device, bindings = _bindings()
    with pytest.raises(ValueError, match="no capability 'onoff'"):
        bindings.register_capability("onoff", "switch", "Relay")


def test_unknown_domain_is_rejected() -> None:
    _device, bindings = _bindings("onoff")
    with pytest.raises(ValueError, match="Unknown ESPHome domain 'relay'"):
        bindings.register_capability("onoff", "relay", "Relay")


def test_app_capability_on_a_multi_value_domain_needs_a_parser() -> None:
    _device, bindings = _bindings("brand_glow")
    with pytest.raises(ValueError, match="pass report_parser or set_parser"):
        bindings.register_capability("brand_glow", "light", "Status LED")


def test_settable_capability_on_a_sensor_is_rejected() -> None:
    _device, bindings = _bindings("garagedoor_closed")
    with pytest.raises(ValueError, match="binary_sensor only reports"):
        bindings.register_capability("garagedoor_closed", "binary_sensor", "Door")


def test_settable_capability_on_a_sensor_binds_with_a_parser() -> None:
    _device, bindings = _bindings("locked")
    bindings.register_capability(
        "locked",
        "binary_sensor",
        "Lock",
        report_parser=lambda state, entity: not state.state,
    )


def test_app_capability_on_a_single_value_domain_uses_the_default() -> None:
    async def run() -> None:
        device, bindings = _bindings("brand_level")
        bindings.register_capability("brand_level", "number", "LED level")
        bindings.bind([LEVEL])
        bindings.handle_state(NumberState(key=3, state=40.0))
        await _settle()
        assert device.written == [("brand_level", 40.0)]

        await device._capability_listeners["brand_level"](55)
        device.client.command.assert_called_once_with("number_command", 3, state=55.0)

    asyncio.run(run())


# --- node -> Homey ----------------------------------------------------------


def test_states_reach_their_capabilities_converted() -> None:
    async def run() -> None:
        device, bindings = _bindings("measure_temperature", "onoff")
        bindings.register_capability("measure_temperature", "sensor", "Temperature")
        bindings.register_capability("onoff", "switch", "Relay")
        bindings.bind([TEMPERATURE, RELAY])

        bindings.handle_state(SensorState(key=4, state=212.0))
        bindings.handle_state(SwitchState(key=1, state=True))
        bindings.handle_state(SwitchState(key=99, state=True))  # not listed
        await _settle()

        assert device.written == [("measure_temperature", 100.0), ("onoff", True)]

    asyncio.run(run())


@pytest.mark.parametrize(
    "state",
    [
        SensorState(key=4, state=21.0, missing_state=True),
        SensorState(key=4, state=float("nan")),
        SensorState(key=4, state=float("inf")),
    ],
)
def test_no_reading_writes_unknown(state: SensorState) -> None:
    async def run() -> None:
        device, bindings = _bindings("measure_temperature")
        bindings.register_capability("measure_temperature", "sensor", "Temperature")
        bindings.bind([TEMPERATURE])
        bindings.handle_state(state)
        await _settle()
        assert device.written == [("measure_temperature", None)]

    asyncio.run(run())


def test_report_parser_returning_none_skips_the_write() -> None:
    async def run() -> None:
        device, bindings = _bindings("onoff")
        bindings.register_capability(
            "onoff", "switch", "Relay", report_parser=lambda state, entity: None
        )
        bindings.bind([RELAY])
        bindings.handle_state(SwitchState(key=1, state=True))
        await _settle()
        assert device.written == []

    asyncio.run(run())


def test_capability_bound_after_the_connect_dump_gets_the_last_state() -> None:
    async def run() -> None:
        device, bindings = _bindings("onoff")
        bindings.bind([RELAY])
        bindings.handle_state(SwitchState(key=1, state=True))
        bindings.register_capability("onoff", "switch", "Relay")
        await _settle()
        assert device.written == [("onoff", True)]

    asyncio.run(run())


def test_state_listener_gets_every_state_and_may_be_async() -> None:
    async def run() -> None:
        _device, bindings = _bindings()
        seen: list[Any] = []

        async def listener(state: Any, entity: Any) -> None:
            seen.append((state.state, entity.name))

        bindings.register_state_listener("switch", "Relay", listener)
        bindings.bind([RELAY])
        bindings.handle_state(SwitchState(key=1, state=False))
        await _settle()
        assert seen == [(False, "Relay")]

    asyncio.run(run())


def test_unregistered_capability_stops_reporting_and_listening() -> None:
    async def run() -> None:
        device, bindings = _bindings("onoff")
        bindings.register_capability("onoff", "switch", "Relay")
        bindings.bind([RELAY])
        bindings.unregister_capability("onoff")
        bindings.handle_state(SwitchState(key=1, state=True))
        await _settle()
        assert device.written == []
        assert "onoff" not in device._capability_listeners

    asyncio.run(run())


def test_sub_devices_with_one_key_stay_apart() -> None:
    async def run() -> None:
        device, bindings = _bindings("onoff.left", "onoff.right")
        left = SwitchInfo(object_id="relay", key=1, name="Relay", device_id=1)
        right = SwitchInfo(object_id="relay", key=1, name="Relay", device_id=2)
        bindings.register_capability("onoff.left", "switch", "Relay", device_id=1)
        bindings.register_capability("onoff.right", "switch", "Relay", device_id=2)
        bindings.bind([left, right])

        bindings.handle_state(SwitchState(key=1, state=True, device_id=2))
        await _settle()
        assert device.written == [("onoff.right", True)]

        await device._capability_listeners["onoff.left"](False)
        device.client.command.assert_called_once_with(
            "switch_command", 1, state=False, device_id=1
        )

    asyncio.run(run())


# --- Homey -> node ----------------------------------------------------------


def test_suffixed_capability_finds_the_system_parser() -> None:
    """``dim.led`` uses the parsers of ``dim``."""

    async def run() -> None:
        device, bindings = _bindings("dim.led")
        bindings.register_capability("dim.led", "light", "Status LED")
        bindings.bind([LED])
        await device._capability_listeners["dim.led"](0.4)
        device.client.command.assert_called_once_with(
            "light_command", 2, state=True, brightness=0.4
        )

    asyncio.run(run())


def test_app_set_parser_wins() -> None:
    async def run() -> None:
        device, bindings = _bindings("onoff")
        bindings.register_capability(
            "onoff",
            "light",
            "Status LED",
            set_parser=lambda value, opts, entity: {"state": value, "effect": "Pulse"},
        )
        bindings.bind([LED])
        await device._capability_listeners["onoff"](True)
        device.client.command.assert_called_once_with(
            "light_command", 2, state=True, effect="Pulse"
        )

    asyncio.run(run())


def test_set_parser_returning_none_sends_nothing() -> None:
    async def run() -> None:
        device, bindings = _bindings("onoff")
        bindings.register_capability(
            "onoff", "switch", "Relay", set_parser=lambda value, opts, entity: None
        )
        bindings.bind([RELAY])
        await device._capability_listeners["onoff"](True)
        device.client.command.assert_not_called()

    asyncio.run(run())


def test_missing_entity_is_logged_and_its_set_fails() -> None:
    async def run() -> None:
        device, bindings = _bindings("onoff")
        bindings.register_capability("onoff", "switch", "Relay")
        bindings.bind([LED])
        assert "No switch entity named 'Relay'" in device.error.call_args.args[0]
        with pytest.raises(RuntimeError, match="errors.entity_missing:switch,Relay"):
            await device._capability_listeners["onoff"](True)

    asyncio.run(run())


def test_offline_node_rejects_a_set() -> None:
    async def run() -> None:
        device, bindings = _bindings("onoff")
        bindings.register_capability("onoff", "switch", "Relay")
        bindings.bind([RELAY])
        device.available = False
        with pytest.raises(RuntimeError, match="device_not_connected"):
            await device._capability_listeners["onoff"](True)

    asyncio.run(run())


def test_hue_and_saturation_are_set_together_once_both_are_bound() -> None:
    async def run() -> None:
        device, bindings = _bindings("light_hue", "light_saturation")
        bindings.register_capability("light_hue", "light", "Status LED")
        assert device.multi == []
        bindings.register_capability("light_saturation", "light", "Status LED")
        assert [ids for ids, _listener in device.multi] == [
            ["light_hue", "light_saturation"]
        ]
        bindings.bind([LED])

        device.values["light_saturation"] = 1.0
        _ids, listener = device.multi[0]
        await listener({"light_hue": 0.0})
        command = device.client.command.call_args
        assert command.args == ("light_command", 2)
        assert command.kwargs["rgb"] == (1.0, 0.0, 0.0)

    asyncio.run(run())


def test_light_mode_switches_to_the_color_the_device_holds() -> None:
    async def run() -> None:
        device, bindings = _bindings("light_mode", "light_hue", "light_saturation")
        for capability_id in ("light_mode", "light_hue", "light_saturation"):
            bindings.register_capability(capability_id, "light", "Status LED")
        bindings.bind([LED])
        device.values.update({"light_hue": 1 / 3, "light_saturation": 1.0})

        await device._capability_listeners["light_mode"]("color")

        rgb = device.client.command.call_args.kwargs["rgb"]
        assert rgb == pytest.approx((0.0, 1.0, 0.0))

    asyncio.run(run())


def test_reconnect_rebinds_to_new_keys() -> None:
    async def run() -> None:
        device, bindings = _bindings("onoff")
        bindings.register_capability("onoff", "switch", "Relay")
        bindings.bind([RELAY])
        rebuilt = SwitchInfo(object_id="relay", key=7, name="Relay")
        bindings.bind([rebuilt])

        bindings.handle_state(SwitchState(key=1, state=True))
        bindings.handle_state(SwitchState(key=7, state=False))
        await _settle()
        assert device.written == [("onoff", False)]

    asyncio.run(run())


def test_entity_lookup_for_an_apps_own_command() -> None:
    _device, bindings = _bindings()
    assert bindings.entity("light", "Status LED") is None
    bindings.bind([LED, LightState()])  # a non-entity is skipped
    entity = bindings.entity("light", "Status LED")
    assert entity is not None
    assert (entity.key, entity.domain) == (2, "light")
