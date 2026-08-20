"""Settings-page fields backed by an ESPHome entity.

`settingEntities` maps a Homey settings key onto an entity object id, because
Homey settings are declared statically per driver and cannot be generated per
device at pair time. These tests pin the two halves that are easy to get wrong:
which command a mapped entity type gets, and when a reported value counts as a
mismatch worth writing.
"""

from __future__ import annotations

from typing import Any

import pytest

from homey_esphomedriver.settings import (
    SETTING_COMMANDS,
    setting_bool,
    setting_matches,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (True, True),
        (False, False),
        ("true", True),
        ("True", True),
        (" 1 ", True),
        ("on", True),
        ("false", False),
        ("0", False),
        ("off", False),
        ("", False),
    ],
)
def testsetting_bool_reads_homeys_stored_forms(raw: Any, expected: bool) -> None:
    """A checkbox may reach the driver as a bool or as text."""
    assert setting_bool(raw) is expected


def testsetting_bool_refuses_anything_else() -> None:
    with pytest.raises(ValueError, match="as a boolean"):
        setting_bool("maybe")


@pytest.mark.parametrize(
    ("wanted", "reported"),
    [
        (21.0, 21.0),
        (21.0, 21.0000001),
        ("21", 21.0),
        ("heat", "heat"),
        (" heat ", "heat"),
        (True, True),
        (False, False),
    ],
)
def test_matching_values_are_not_rewritten(wanted: Any, reported: Any) -> None:
    """The node is authoritative for what it holds; only a real drift writes."""
    assert setting_matches(wanted, reported) is True


@pytest.mark.parametrize(
    ("wanted", "reported"),
    [
        (21.0, 22.0),
        (21.0, 21.1),
        ("heat", "cool"),
        (True, False),
    ],
)
def test_differing_values_are_a_mismatch(wanted: Any, reported: Any) -> None:
    assert setting_matches(wanted, reported) is False


def test_a_dropdown_is_compared_as_text_not_forced_through_float() -> None:
    """Forcing a select through `float` would raise, or worse, compare equal."""
    assert setting_matches("auto", "auto") is True
    assert setting_matches("auto", "manual") is False


def test_each_mapped_entity_type_gets_its_own_command() -> None:
    """A `settingEntities` mapping names an object id, so the entity type is
    whatever the YAML author chose. Writing every one of them as a number sends
    a dropdown a float it rejects and a switch a value it ignores.
    """
    from aioesphomeapi import NumberInfo, SelectInfo, SwitchInfo

    assert SETTING_COMMANDS[NumberInfo][0] == "number_command"
    assert SETTING_COMMANDS[SelectInfo][0] == "select_command"
    assert SETTING_COMMANDS[SwitchInfo][0] == "switch_command"

    assert SETTING_COMMANDS[NumberInfo][1]("21.5") == 21.5
    assert SETTING_COMMANDS[SelectInfo][1](21) == "21"
    assert SETTING_COMMANDS[SwitchInfo][1]("off") is False
