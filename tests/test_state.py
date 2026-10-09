"""Entity state handlers pin missing_state as unknown Homey values."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aioesphomeapi import SwitchState

from homey_esphomedriver.entities.state.climate import ClimateEntityStateUpdateHandler
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
    await handler.handle(state, capabilities)  # type: ignore[attr-defined]
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
