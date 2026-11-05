"""Entity state handlers pin missing_state as unknown Homey values."""

from __future__ import annotations

import asyncio
import math
from types import SimpleNamespace

import pytest
from aioesphomeapi import ClimateState, Event, SensorState, SwitchState

from homey_esphomedriver.entities.state.base import AbstractEntityStateUpdateHandler
from homey_esphomedriver.entities.state.climate import ClimateEntityStateUpdateHandler
from homey_esphomedriver.entities.state.event import EventEntityStateUpdateHandler
from homey_esphomedriver.entities.state.sensor import SensorEntityStateUpdateHandler
from homey_esphomedriver.entities.state.switch import SwitchEntityStateUpdateHandler
from homey_esphomedriver.entities.state.water_heater import (
    WaterHeaterEntityStateUpdateHandler,
)


class _Device:
    pass


async def _writes(
    handler: object, state: object, capabilities: list[str]
) -> list[tuple[str, object]]:
    writes: list[tuple[str, object]] = []
    handler.set_capability_value = lambda cap, val: writes.append((cap, val))  # type: ignore[attr-defined]
    handler.handle(state, capabilities)  # type: ignore[attr-defined]
    return writes


def test_missing_state_clears_switch_climate_water_heater() -> None:
    """Unpublished switch/climate/water-heater state must not look like off."""

    async def run() -> None:
        device = _Device()
        unknown = SimpleNamespace(missing_state=True, state=False)
        assert await _writes(
            SwitchEntityStateUpdateHandler(device),
            unknown,
            ["onoff"],
        ) == [("onoff", None)]
        assert await _writes(
            ClimateEntityStateUpdateHandler(device),
            unknown,
            ["onoff", "thermostat_mode", "measure_temperature"],
        ) == [
            ("onoff", None),
            ("thermostat_mode", None),
            ("measure_temperature", None),
        ]
        assert await _writes(
            WaterHeaterEntityStateUpdateHandler(device),
            unknown,
            ["onoff", "heater_operation_mode"],
        ) == [("onoff", None), ("heater_operation_mode", None)]
        assert await _writes(
            SwitchEntityStateUpdateHandler(device),
            SwitchState(key=1, state=True),
            ["onoff"],
        ) == [("onoff", True)]

    asyncio.run(run())


def test_event_triggers_flow_then_schedules_idle() -> None:
    """Event handling stays sync; the Flow trigger runs before the idle timer."""
    calls: list[tuple[object, ...]] = []

    class _Flow:
        async def trigger_event(
            self, device: object, capability: str, value: object = None
        ) -> None:
            calls.append(("trigger", capability, value))

    class _Homey:
        def set_timeout(self, callback: object, ms: int) -> int:
            calls.append(("idle", ms))
            return 1

        def clear_timeout(self, timeout_id: int) -> None:
            pass

    class _EventDevice:
        driver = SimpleNamespace(_flow=_Flow())
        homey = _Homey()

        async def set_capability_value(self, capability: str, value: object) -> None:
            calls.append(("set", capability, value))

    async def run() -> None:
        handler = EventEntityStateUpdateHandler(_EventDevice())
        handler.handle(Event(key=1, event_type="single_press"), ["event_button.front"])
        assert calls == []
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert calls == [
            ("set", "event_button.front", "single_press"),
            ("trigger", "event_button.front", "Single Press"),
            ("idle", 1000),
        ]

    asyncio.run(run())


def test_missing_state_writes_unknown_without_flow_trigger() -> None:
    """Going unknown (None) is written but fires no sub-capability Flow card."""
    calls: list[tuple[object, ...]] = []

    class _Flow:
        async def trigger_subcapability(
            self, device: object, capability: str, value: object
        ) -> None:
            calls.append(("trigger", capability, value))

    class _SubDevice:
        driver = SimpleNamespace(_flow=_Flow())

        async def set_capability_value(self, capability: str, value: object) -> None:
            calls.append(("set", capability, value))

    async def run() -> None:
        handler = SensorEntityStateUpdateHandler(_SubDevice())
        await handler._set_capability_value_and_trigger(
            "esphome_number.humidex", None, 21.5
        )
        await handler._set_capability_value_and_trigger(
            "esphome_number.humidex", 22.0, None
        )
        assert calls == [
            ("set", "esphome_number.humidex", None),
            ("set", "esphome_number.humidex", 22.0),
            ("trigger", "esphome_number.humidex", 22.0),
        ]

    asyncio.run(run())


class _CapabilityDevice:
    """Records awaited capability writes; every capability exists."""

    def __init__(self) -> None:
        self.written: list[tuple[str, object]] = []

        class _Flow:
            async def trigger_subcapability(self, *args: object) -> None:
                pass

        self.driver = SimpleNamespace(_flow=_Flow())

    def has_capability(self, capability_id: str) -> bool:
        return True

    def get_capability_value(self, capability_id: str) -> object:
        return None

    def get_capability_options(self, capability_id: str) -> dict[str, object]:
        return {}

    async def set_capability_value(self, capability_id: str, value: object) -> None:
        self.written.append((capability_id, value))


async def _flush(
    device: _CapabilityDevice, handler: object, state: object, caps: list[str]
) -> None:
    handler.handle(state, caps)  # type: ignore[attr-defined]
    for _ in range(3):
        await asyncio.sleep(0)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_set_capability_value_writes_non_finite_as_unknown(value: float) -> None:
    """Homey IPC is strict JSON: NaN/Infinity must never reach a capability write."""

    async def run() -> None:
        device = _CapabilityDevice()
        handler = AbstractEntityStateUpdateHandler(device)  # type: ignore[arg-type]
        handler.set_capability_value("dim", value)
        handler.set_capability_value("measure_power", 12.5)
        for _ in range(3):
            await asyncio.sleep(0)
        assert device.written == [("dim", None), ("measure_power", 12.5)]

    asyncio.run(run())


def test_climate_nan_before_first_reading_is_unknown() -> None:
    """Issue #15: a climate entity reports NaN temperatures until it has a reading."""

    async def run() -> None:
        device = _CapabilityDevice()
        state = ClimateState(
            key=1,
            current_temperature=math.nan,
            target_temperature=math.inf,
            current_humidity=math.nan,
        )
        await _flush(
            device,
            ClimateEntityStateUpdateHandler(device),  # type: ignore[arg-type]
            state,
            ["measure_temperature", "target_temperature", "measure_humidity"],
        )
        assert device.written == [
            ("measure_temperature", None),
            ("target_temperature", None),
            ("measure_humidity", None),
        ]

    asyncio.run(run())


@pytest.mark.parametrize("value", [math.inf, -math.inf])
def test_sensor_infinity_is_unknown(value: float) -> None:
    """Infinity is treated like NaN, including for uptime (int(inf) would raise)."""

    async def run() -> None:
        device = _CapabilityDevice()
        handler = SensorEntityStateUpdateHandler(device)  # type: ignore[arg-type]
        await _flush(
            device, handler, SensorState(key=1, state=value), ["measure_uptime"]
        )
        assert device.written == [("measure_uptime", None)]

    asyncio.run(run())
