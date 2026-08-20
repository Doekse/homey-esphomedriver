"""Pair-time mapping helper tests.

Pins object-id alias matching (exact / suffix / unit / ``unless_device_class``),
device-class lookup, picker option shape, ESPHome temperature-unit conversion,
and the hidden bare ids ``add_suffixed`` adds so Homey Flow ``$filter`` can match.
"""

from __future__ import annotations

from typing import cast

import pytest
from aioesphomeapi import (
    BinarySensorInfo,
    ButtonInfo,
    EntityCategory,
    EntityInfo,
    TemperatureUnit,
)

from homey_esphomedriver.esphome_types import HomeyEspHomeDeviceOption
from homey_esphomedriver.mapping import (
    REFRESH_CAPABILITY,
    REFRESH_CAPABILITY_OPTIONS,
    DeviceEntityMapper,
    ObjectIdAlias,
    celsius_step,
    lookup_device_class,
    match_object_id_alias,
    picker_values,
    temperature_unit_label,
    to_celsius,
)


def aliases() -> tuple[ObjectIdAlias, ...]:
    return (
        ObjectIdAlias("measure_uptime", exact=("uptime",)),
        ObjectIdAlias(
            "measure_dew_point",
            exact=("dew_point",),
            suffixes=("_dew_point",),
        ),
        ObjectIdAlias(
            "measure_wind_strength",
            units=("m/s", "km/h"),
            unless_device_class=("precipitation",),
        ),
    )


def mapped_device(*entities: EntityInfo) -> HomeyEspHomeDeviceOption:
    homey_device = cast(
        HomeyEspHomeDeviceOption,
        {
            "name": "node",
            "data": {},
            "store": {},
            "settings": {},
            "capabilities": [],
            "capabilitiesOptions": {},
        },
    )
    DeviceEntityMapper.map(list(entities), homey_device)
    return homey_device


def test_match_object_id_alias_exact_is_case_insensitive() -> None:
    match = match_object_id_alias("Uptime", None, "", aliases())
    assert match is not None
    assert match.capability == "measure_uptime"


def test_match_object_id_alias_suffix() -> None:
    match = match_object_id_alias("outdoor_dew_point", None, "", aliases())
    assert match is not None
    assert match.capability == "measure_dew_point"


def test_match_object_id_alias_unit() -> None:
    match = match_object_id_alias("anemometer", "km/h", "", aliases())
    assert match is not None
    assert match.capability == "measure_wind_strength"


def test_match_object_id_alias_skips_unless_device_class() -> None:
    match = match_object_id_alias("anemometer", "km/h", "precipitation", aliases())
    assert match is None


def test_match_object_id_alias_first_match_wins() -> None:
    table = (
        ObjectIdAlias("first", exact=("speed",)),
        ObjectIdAlias("second", exact=("speed",)),
    )
    match = match_object_id_alias("speed", None, "", table)
    assert match is not None
    assert match.capability == "first"


def test_match_object_id_alias_returns_none_when_unmatched() -> None:
    assert match_object_id_alias("relay", None, "", aliases()) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Temperature", "measure_temperature"),
        (None, None),
        ("", None),
        ("unknown", None),
    ],
)
def test_lookup_device_class(value: str | None, expected: str | None) -> None:
    mapping = {"temperature": "measure_temperature"}
    assert lookup_device_class(value, mapping) == expected


def test_picker_values_shape() -> None:
    assert picker_values([("heat", "Heat"), ("cool", "Cool")]) == [
        {"id": "heat", "title": {"en": "Heat"}},
        {"id": "cool", "title": {"en": "Cool"}},
    ]


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        (TemperatureUnit.FAHRENHEIT, "°F"),
        (TemperatureUnit.KELVIN, "K"),
        (TemperatureUnit.CELSIUS, "°C"),
        (None, "°C"),
    ],
)
def test_temperature_unit_label(unit: TemperatureUnit | None, expected: str) -> None:
    assert temperature_unit_label(unit) == expected


@pytest.mark.parametrize(
    ("unit", "value", "expected"),
    [
        (TemperatureUnit.CELSIUS, 21.0, 21.0),
        (None, 21.0, 21.0),
        (TemperatureUnit.FAHRENHEIT, 32.0, 0.0),
        (TemperatureUnit.KELVIN, 273.15, 0.0),
    ],
)
def test_to_celsius(
    unit: TemperatureUnit | None,
    value: float,
    expected: float,
) -> None:
    assert to_celsius(unit, value) == pytest.approx(expected)


def test_celsius_step_scales_fahrenheit_only() -> None:
    """Kelvin and Celsius steps are already Homey °C; Fahrenheit is not."""
    assert celsius_step(TemperatureUnit.FAHRENHEIT, 1.8) == pytest.approx(1.0)
    assert celsius_step(TemperatureUnit.KELVIN, 0.5) == 0.5
    assert celsius_step(None, 0.5) == 0.5


def test_suffixed_custom_cap_adds_hidden_flow_filter_marker() -> None:
    """Bare ``esphome_boolean`` exists only so Homey ``$filter`` can match."""
    homey_device = mapped_device(
        BinarySensorInfo(object_id="screen_button", key=1, name="Screen"),
        BinarySensorInfo(object_id="flag", key=2, name="Flag"),
    )
    assert homey_device["capabilities"] == [
        "esphome_boolean",
        "esphome_boolean.screen_button",
        "esphome_boolean.flag",
    ]
    marker = homey_device["capabilitiesOptions"]["esphome_boolean"]
    assert marker == {"uiComponent": None}


def test_button_entity_adds_custom_flow_filter_marker() -> None:
    """Bare ``esphome_button`` exists only so Homey ``$filter`` can match ``button.*``."""
    homey_device = mapped_device(
        ButtonInfo(object_id="press_me", key=1, name="Press"),
        ButtonInfo(object_id="reset", key=2, name="Reset"),
    )
    assert homey_device["capabilities"] == [
        "esphome_button",
        "button.press_me",
        "button.reset",
    ]
    marker = homey_device["capabilitiesOptions"]["esphome_button"]
    assert marker == {"uiComponent": None}


def test_map_device_attaches_refresh() -> None:
    homey_device = mapped_device()
    DeviceEntityMapper.map_device([], homey_device)
    assert homey_device["capabilities"] == [REFRESH_CAPABILITY]
    assert (
        homey_device["capabilitiesOptions"][REFRESH_CAPABILITY]
        == REFRESH_CAPABILITY_OPTIONS
    )


def test_map_device_includes_diagnostic_entities() -> None:
    entity = BinarySensorInfo(
        object_id="status",
        key=1,
        name="Status",
        entity_category=EntityCategory.DIAGNOSTIC,
    )
    assert mapped_device(entity)["capabilities"] == []

    homey_device = mapped_device()
    DeviceEntityMapper.map_device([entity], homey_device, diagnostics=True)
    assert homey_device["capabilities"] == [
        "esphome_boolean",
        "esphome_boolean.status",
        REFRESH_CAPABILITY,
    ]
