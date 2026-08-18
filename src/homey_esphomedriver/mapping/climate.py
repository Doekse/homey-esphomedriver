"""Map ESPHome ClimateInfo onto Homey climate capabilities.

Picker values for thermostat, fan, and swing mode are slimmed to Homey ids.
"""

from __future__ import annotations

from typing import cast

from aioesphomeapi import (
    ClimateFanMode,
    ClimateInfo,
    ClimateMode,
    ClimateSwingMode,
    EntityInfo,
    TemperatureUnit,
)

from homey_esphomedriver.esphome_types import HomeyEspHomeDeviceOption
from homey_esphomedriver.mapping import (
    DeviceEntityMapper,
    celsius_step,
    picker_values,
    temperature_unit_label,
    to_celsius,
)


class ClimateEntityMapper:
    def map(
        self,
        entity: EntityInfo,
        homey_device: HomeyEspHomeDeviceOption,
    ) -> None:
        if DeviceEntityMapper.has_entity_type(homey_device, "climate"):
            return

        info = cast(ClimateInfo, entity)
        modes = info.supported_modes
        cooling = {
            ClimateMode.COOL,
            ClimateMode.HEAT_COOL,
            ClimateMode.DRY,
            ClimateMode.FAN_ONLY,
        }
        DeviceEntityMapper.set_device_class(
            homey_device,
            "thermostat"
            if ClimateMode.HEAT in modes and not cooling.intersection(modes)
            else "airconditioning",
        )

        unit = info.temperature_unit or TemperatureUnit.CELSIUS
        on_mode = next(
            (
                candidate
                for candidate in (
                    ClimateMode.HEAT_COOL,
                    ClimateMode.AUTO,
                    ClimateMode.HEAT,
                    ClimateMode.COOL,
                )
                if candidate in modes
            ),
            next(mode for mode in modes if mode != ClimateMode.OFF),
        )

        DeviceEntityMapper.add_capability(
            homey_device,
            info.key,
            "thermostat_mode",
            {"values": _thermostat_values(modes)},
        )
        DeviceEntityMapper.add_indexed(
            homey_device,
            info.key,
            "onoff",
            {"climate_on_mode": int(on_mode)},
        )

        temp_options: dict[str, object] = {
            "esphome_unit": temperature_unit_label(unit),
            "min": to_celsius(unit, info.visual_min_temperature),
            "max": to_celsius(unit, info.visual_max_temperature),
            "step": celsius_step(unit, info.visual_target_temperature_step),
        }
        if info.supports_two_point_target_temperature:
            for base in ("target_temperature_min", "target_temperature_max"):
                DeviceEntityMapper.add_capability(
                    homey_device,
                    info.key,
                    base,
                    temp_options,
                )
        else:
            DeviceEntityMapper.add_capability(
                homey_device,
                info.key,
                "target_temperature",
                temp_options,
            )

        if info.supports_target_humidity:
            DeviceEntityMapper.add_capability(
                homey_device,
                info.key,
                "target_humidity",
                {
                    "min": info.visual_min_humidity,
                    "max": info.visual_max_humidity,
                },
            )

        fan_values = _climate_fan_values(
            info.supported_fan_modes,
            info.supported_custom_fan_modes,
        )
        if fan_values:
            DeviceEntityMapper.add_capability(
                homey_device,
                info.key,
                "fan_mode",
                {"values": fan_values},
            )

        swing_values = _swing_values(info.supported_swing_modes)
        if swing_values:
            DeviceEntityMapper.add_capability(
                homey_device,
                info.key,
                "swing_mode",
                {"values": swing_values},
            )

        if info.supports_current_temperature:
            DeviceEntityMapper.add_capability(
                homey_device,
                info.key,
                "measure_temperature",
                {"esphome_unit": temperature_unit_label(unit)},
            )

        if info.supports_current_humidity:
            DeviceEntityMapper.add_capability(
                homey_device,
                info.key,
                "measure_humidity",
            )


def _thermostat_values(modes: list[ClimateMode]) -> list[dict[str, object]]:
    titles = {
        ClimateMode.HEAT_COOL: ("auto", "Automatic"),
        ClimateMode.AUTO: ("auto", "Automatic"),
        ClimateMode.HEAT: ("heat", "Heat"),
        ClimateMode.COOL: ("cool", "Cool"),
        ClimateMode.OFF: ("off", "Off"),
    }
    by_id: dict[str, tuple[str, str]] = {}
    for mode in modes:
        mapped = titles.get(mode)
        if mapped is not None:
            by_id[mapped[0]] = mapped
    return picker_values(
        by_id[mode_id]
        for mode_id in ("auto", "heat", "cool", "off")
        if mode_id in by_id
    )


def _swing_values(modes: list[ClimateSwingMode]) -> list[dict[str, object]]:
    if not modes or modes == [ClimateSwingMode.OFF]:
        return []
    present = set(modes)
    present.add(ClimateSwingMode.OFF)
    titles = {
        ClimateSwingMode.OFF: ("off", "Off"),
        ClimateSwingMode.VERTICAL: ("vertical", "Vertical"),
        ClimateSwingMode.HORIZONTAL: ("horizontal", "Horizontal"),
        ClimateSwingMode.BOTH: ("both", "Both"),
    }
    return picker_values(
        titles[mode]
        for mode in (
            ClimateSwingMode.OFF,
            ClimateSwingMode.VERTICAL,
            ClimateSwingMode.HORIZONTAL,
            ClimateSwingMode.BOTH,
        )
        if mode in present
    )


def _climate_fan_values(
    modes: list[ClimateFanMode],
    custom_modes: list[str],
) -> list[dict[str, object]]:
    entries: list[tuple[str, str]] = []
    if ClimateFanMode.AUTO in modes:
        entries.append(("auto", "Auto"))
    if custom_modes or any(
        mode not in (ClimateFanMode.OFF, ClimateFanMode.AUTO) for mode in modes
    ):
        entries.append(("on", "On"))
    if ClimateFanMode.OFF in modes:
        entries.append(("off", "Off"))
    return picker_values(entries)
