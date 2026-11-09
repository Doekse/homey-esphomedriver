"""Sensor: any capability takes the reading, converted to the capability's unit."""

from __future__ import annotations

from typing import Any, cast

from aioesphomeapi import SensorInfo

from homey_esphomedriver.system import BoundEntity, SystemCapability
from homey_esphomedriver.units import convert_unit

REPORTS_ONLY = True

CAPABILITIES: dict[str, SystemCapability] = {}


def default(capability_id: str) -> SystemCapability:
    """A ``measure_*`` / ``meter_*`` or app capability takes the reading."""

    def report(state: Any, entity: BoundEntity) -> Any:
        unit = cast(SensorInfo, entity.info).unit_of_measurement
        return convert_unit(capability_id, unit, float(state.state))

    return SystemCapability(report_parser=report)
