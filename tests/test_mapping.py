"""Pair-time mapping helper tests.

Pins object-id alias matching (exact / suffix / unit / ``unless_device_class``),
device-class lookup, picker option shape, and ESPHome temperature-unit
conversion used when writing capability options.
"""

from __future__ import annotations

import pytest
from aioesphomeapi import TemperatureUnit

from homey_esphomedriver.mapping import (
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
