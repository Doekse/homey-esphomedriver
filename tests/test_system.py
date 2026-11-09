"""System capabilities: the default parsers per Homey capability and domain.

Each test runs a parser the way the bindings do, with a bound entity carrying
what the node listed.
"""

from __future__ import annotations

from typing import Any

import pytest
from aioesphomeapi import (
    AlarmControlPanelCommand,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelEntityState,
    AlarmControlPanelInfo,
    AlarmControlPanelState,
    BinarySensorInfo,
    BinarySensorState,
    ClimateFanMode,
    ClimateInfo,
    ClimateMode,
    ClimateState,
    ColorMode,
    CoverInfo,
    CoverOperation,
    CoverState,
    EntityInfo,
    FanInfo,
    FanState,
    LightInfo,
    LightState,
    LockCommand,
    LockEntityState,
    LockInfo,
    LockState,
    MediaPlayerCommand,
    MediaPlayerInfo,
    SensorInfo,
    SensorState,
    TemperatureUnit,
    WaterHeaterInfo,
    WaterHeaterState,
    WaterHeaterStateFlag,
)

from homey_esphomedriver.system import (
    BoundEntity,
    SystemCapability,
    domain_of,
    lookup,
)
from homey_esphomedriver.units import mireds_to_kelvin


class _Device:
    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self.values = values or {}

    def get_capability_value(self, capability_id: str) -> Any:
        return self.values.get(capability_id)


def _entity(
    info: EntityInfo, capabilities: tuple[str, ...] = (), **values: Any
) -> BoundEntity:
    domain = domain_of(info)
    assert domain is not None
    return BoundEntity(
        device=_Device(values),  # type: ignore[arg-type]
        info=info,
        domain=domain,
        capabilities=capabilities,
    )


def _system(capability_id: str, entity: BoundEntity) -> SystemCapability:
    found = lookup(capability_id, entity.domain)
    assert found is not None
    return found


def _report(capability_id: str, entity: BoundEntity, state: Any) -> Any:
    parser = _system(capability_id, entity).report_parser
    assert parser is not None
    return parser(state, entity)


def _set(capability_id: str, entity: BoundEntity, value: Any) -> Any:
    parser = _system(capability_id, entity).set_parser
    assert parser is not None
    return parser(value, {}, entity)


# --- lookup -----------------------------------------------------------------


def test_lookup_falls_back_to_the_base_then_the_domain_default() -> None:
    assert lookup("dim.led", "light") is lookup("dim", "light")
    assert lookup("measure_co2", "sensor") is not None
    assert lookup("brand_glow", "light") is None
    assert lookup("onoff", "camera") is None


@pytest.mark.parametrize(
    ("capability_id", "domain"),
    [
        ("locked", "binary_sensor"),
        ("garagedoor_closed.door", "binary_sensor"),
        ("onoff", "binary_sensor"),
        ("target_temperature", "sensor"),
        ("thermostat_mode", "text_sensor"),
        ("button", "event"),
    ],
)
def test_entity_that_only_reports_has_no_settable_capability(
    capability_id: str, domain: str
) -> None:
    assert lookup(capability_id, domain) is None


def test_entity_that_only_reports_binds_capabilities_that_only_show() -> None:
    assert lookup("alarm_contact", "binary_sensor") is not None
    assert lookup("measure_temperature", "sensor") is not None
    assert lookup("level_co2", "text_sensor") is not None
    assert lookup("brand_reading", "sensor") is not None


def test_domain_of_a_text_entity_is_text() -> None:
    from aioesphomeapi import TextInfo

    assert domain_of(TextInfo()) == "text"
    assert domain_of(LightState()) is None  # type: ignore[arg-type]


# --- single-value domains ---------------------------------------------------


def test_sensor_converts_from_the_entity_unit() -> None:
    entity = _entity(SensorInfo(unit_of_measurement="kW"))
    assert _report("measure_power", entity, SensorState(state=1.5)) == 1500.0
    assert _report("brand_reading", entity, SensorState(state=1.5)) == 1.5


@pytest.mark.parametrize(
    ("capability_id", "state", "expected"),
    [
        ("alarm_motion", True, True),
        ("alarm_connectivity", True, False),
        ("battery_charging_state", True, "charging"),
    ],
)
def test_binary_sensor(capability_id: str, state: bool, expected: Any) -> None:
    entity = _entity(BinarySensorInfo())
    assert _report(capability_id, entity, BinarySensorState(state=state)) == expected


# --- light ------------------------------------------------------------------


LIGHT = LightInfo(key=2, min_mireds=153, max_mireds=500)


def test_light_dim_off_at_zero() -> None:
    entity = _entity(LIGHT)
    assert _set("dim", entity, 0.0) == {"state": False}
    assert _set("dim", entity, 0.5) == {"state": True, "brightness": 0.5}


def test_light_temperature_round_trips_across_the_lights_range() -> None:
    entity = _entity(LIGHT)
    warm = _set("light_temperature", entity, 1.0)
    assert warm["color_temperature"] == pytest.approx(500, rel=1e-3)
    state = LightState(color_temperature=500)
    assert _report("light_temperature", entity, state) == pytest.approx(1.0, abs=1e-3)
    assert _report("light_temperature", entity, LightState()) is None


def test_light_mode_follows_the_color_mode() -> None:
    entity = _entity(LIGHT)
    assert _report("light_mode", entity, LightState(color_mode=ColorMode.RGB)) == (
        "color"
    )
    assert (
        _report("light_mode", entity, LightState(color_mode=ColorMode.COLD_WARM_WHITE))
        == "temperature"
    )
    assert _report("light_mode", entity, LightState(color_mode=ColorMode.WHITE)) is None


def test_light_mode_temperature_uses_the_held_temperature() -> None:
    entity = _entity(LIGHT, ("light_temperature",), light_temperature=0.0)
    command = _set("light_mode", entity, "temperature")
    assert mireds_to_kelvin(command["color_temperature"]) == pytest.approx(
        mireds_to_kelvin(153), rel=1e-3
    )


# --- climate ----------------------------------------------------------------


FAHRENHEIT = ClimateInfo(
    supported_modes=[ClimateMode.OFF, ClimateMode.HEAT, ClimateMode.COOL],
    supported_fan_modes=[ClimateFanMode.LOW, ClimateFanMode.HIGH],
    supported_custom_fan_modes=["Turbo"],
    temperature_unit=TemperatureUnit.FAHRENHEIT,
)


def test_climate_target_temperature_is_celsius_both_ways() -> None:
    entity = _entity(FAHRENHEIT)
    state = ClimateState(target_temperature=212.0)
    assert _report("target_temperature", entity, state) == pytest.approx(100.0)
    assert _set("target_temperature", entity, 100.0) == {
        "target_temperature": pytest.approx(212.0)
    }


def test_climate_turns_on_in_the_first_supported_mode() -> None:
    entity = _entity(FAHRENHEIT)
    assert _set("onoff", entity, True) == {"mode": ClimateMode.HEAT}
    assert _set("onoff", entity, False) == {"mode": ClimateMode.OFF}
    assert _set("thermostat_mode", entity, "auto") == {"mode": ClimateMode.HEAT_COOL}


def test_climate_fan_mode_reports_only_listed_modes() -> None:
    entity = _entity(FAHRENHEIT)
    assert _report("fan_mode", entity, ClimateState(fan_mode=ClimateFanMode.HIGH)) == (
        "high"
    )
    assert _report("fan_mode", entity, ClimateState(fan_mode=ClimateFanMode.AUTO)) is (
        None
    )
    assert _report("fan_mode", entity, ClimateState(custom_fan_mode="Turbo")) == "Turbo"
    assert _set("fan_mode", entity, "Turbo") == {"custom_fan_mode": "Turbo"}
    assert _set("fan_mode", entity, "low") == {"fan_mode": ClimateFanMode.LOW}


# --- other domains ----------------------------------------------------------


def test_cover_garage_door_is_closed_only_when_idle() -> None:
    entity = _entity(CoverInfo())
    moving = CoverState(position=0.0, current_operation=CoverOperation.IS_CLOSING)
    idle = CoverState(position=0.0, current_operation=CoverOperation.IDLE)
    assert _report("garagedoor_closed", entity, moving) is None
    assert _report("garagedoor_closed", entity, idle) is True
    assert _report("windowcoverings_state", entity, moving) == "down"
    assert _set("windowcoverings_state", entity, "idle") == {"stop": True}


def test_fan_speed_moves_in_the_fans_steps() -> None:
    entity = _entity(FanInfo(supported_speed_count=4))
    assert _report("fan_speed", entity, FanState(speed_level=2)) == 0.5
    assert _set("fan_speed", entity, 0.75) == {"state": True, "speed_level": 3}
    assert _set("fan_speed", entity, 0.0) == {"state": False}


def test_lock_and_jam() -> None:
    entity = _entity(LockInfo())
    assert _report("locked", entity, LockEntityState(state=LockState.LOCKED)) is True
    jammed = LockEntityState(state=LockState.JAMMED)
    assert _report("alarm_door_fault", entity, jammed) is True
    assert _set("locked", entity, False) == {"command": LockCommand.UNLOCK}


@pytest.mark.parametrize(
    ("info", "command"),
    [
        (MediaPlayerInfo(supports_pause=True), MediaPlayerCommand.PAUSE),
        (MediaPlayerInfo(supports_pause=False), MediaPlayerCommand.STOP),
    ],
)
def test_media_player_pauses_when_it_can(
    info: MediaPlayerInfo, command: MediaPlayerCommand
) -> None:
    assert _set("speaker_playing", _entity(info), False) == {"command": command}


def test_alarm_arms_with_a_supported_command() -> None:
    entity = _entity(
        AlarmControlPanelInfo(
            supported_features=AlarmControlPanelEntityFeature.ARM_NIGHT
        )
    )
    assert _set("homealarm_state", entity, "partially_armed") == {
        "command": AlarmControlPanelCommand.ARM_NIGHT
    }
    with pytest.raises(ValueError, match="armed"):
        _set("homealarm_state", entity, "armed")
    state = AlarmControlPanelEntityState(state=AlarmControlPanelState.ARMING)
    assert _report("homealarm_state", entity, state) is None


def test_water_heater_on_flag_and_temperature() -> None:
    entity = _entity(WaterHeaterInfo(temperature_unit=TemperatureUnit.FAHRENHEIT))
    state = WaterHeaterState(state=WaterHeaterStateFlag.ON, current_temperature=212.0)
    assert _report("onoff", entity, state) is True
    assert _report("measure_temperature", entity, state) == pytest.approx(100.0)
    assert _system("measure_temperature", entity).set_parser is None
    assert _set("onoff", entity, False) == {"on": False}
