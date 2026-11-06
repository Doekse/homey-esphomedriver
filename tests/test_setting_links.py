"""Linking a Homey setting to the ESPHome entity behind it.

A brand driver links a setting to an entity on the setting itself
(``settings[].esphome.entity``), the way Z-Wave drivers put ``zwave`` on each
setting. These tests pin how a manifest link is parsed, how it is bound to an
entity key on the node, and when two values count as the same setting value.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from aioesphomeapi import NumberInfo, SelectInfo, SensorInfo, SwitchInfo

from homey_esphomedriver.entities.mapping import DeviceEntityMapper
from homey_esphomedriver.profile import BrandProfile
from homey_esphomedriver.settings.links import (
    SettingEntity,
    bind_setting_entities,
    parse_setting_entities,
    setting_matches,
)

OFFSET = NumberInfo(object_id="temp_offset", key=11, name="Offset")
MODE = SelectInfo(object_id="mode", key=12, name="Mode", options=["eco", "boost"])
BEEP = SwitchInfo(object_id="beep", key=13, name="Beep")

LINKS = {
    "offset": SettingEntity("temp_offset", "number"),
    "mode": SettingEntity("mode", "dropdown"),
}
BINDINGS = {
    "offset": {"key": 11, "domain": "number"},
    "mode": {"key": 12, "domain": "select"},
}


# --- manifest parsing -------------------------------------------------------


def test_links_are_read_from_settings_including_groups() -> None:
    profile = BrandProfile.from_manifest(
        {
            "settings": [
                {"id": "host", "type": "text"},
                {
                    "id": "offset",
                    "type": "number",
                    "esphome": {"entity": "temp_offset"},
                },
                {
                    "type": "group",
                    "children": [
                        {
                            "id": "mode",
                            "type": "dropdown",
                            "esphome": {"entity": "mode"},
                        }
                    ],
                },
            ]
        }
    )
    assert profile.setting_entities == LINKS


def test_esphome_object_and_setting_links_combine() -> None:
    profile = BrandProfile.from_manifest(
        {
            "esphome": {"projects": ["acme.air"]},
            "settings": [
                {"id": "offset", "type": "number", "esphome": {"entity": "temp_offset"}}
            ],
        }
    )
    assert profile.projects == frozenset({"acme.air"})
    assert profile.setting_entities == {"offset": LINKS["offset"]}


def test_unsupported_type_and_duplicate_entity_are_ignored() -> None:
    links = parse_setting_entities(
        [
            {"id": "label", "type": "text", "esphome": {"entity": "temp_offset"}},
            {"id": "first", "type": "number", "esphome": {"entity": "temp_offset"}},
            {"id": "second", "type": "number", "esphome": {"entity": "temp_offset"}},
            {"type": "number", "esphome": {"entity": "other"}},
        ]
    )
    assert links == {"first": SettingEntity("temp_offset", "number")}


def test_mapped_entity_leaves_the_tile() -> None:
    """The settings page is the entity's one writer."""
    profile = BrandProfile(setting_entities=LINKS)
    assert profile.skip_entity(OFFSET) is True
    assert profile.skip_entity(BEEP) is False


def test_linked_entity_leaves_the_tile_after_replace() -> None:
    """``from_manifest`` adds links with ``replace``; the tile filter follows."""
    profile = BrandProfile().replace(setting_entities=LINKS)
    assert profile.skip_entity(OFFSET) is True


@pytest.mark.parametrize(
    "esphome",
    [
        {"deviceEntities": {"temp_offset": "measure_temperature"}},
        {"capabilityOverrides": {"temp_offset": {"number": "esphome_number.x"}}},
    ],
)
def test_linked_entity_that_is_also_remapped_is_logged(
    esphome: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="homey_esphomedriver.profile"):
        profile = BrandProfile.from_manifest(
            {
                "esphome": esphome,
                "settings": [
                    {
                        "id": "offset",
                        "type": "number",
                        "esphome": {"entity": "temp_offset"},
                    }
                ],
            }
        )
    assert profile.skip_entity(OFFSET) is True
    assert "'offset'" in caplog.text
    assert "'temp_offset'" in caplog.text


# --- binding ----------------------------------------------------------------


def test_bindings_follow_the_entity_domain() -> None:
    assert bind_setting_entities([OFFSET, MODE, BEEP], LINKS) == BINDINGS


def test_missing_or_mistyped_entity_is_left_unbound() -> None:
    links = {
        "offset": SettingEntity("temp_offset", "checkbox"),
        "gone": SettingEntity("gone", "number"),
        "reading": SettingEntity("reading", "number"),
    }
    reading = SensorInfo(object_id="reading", key=14, name="Reading")
    # None records that each link was checked, so it is not looked up again.
    assert bind_setting_entities([OFFSET, reading], links) == {
        "offset": None,
        "gone": None,
        "reading": None,
    }


def test_pairing_stores_bindings_and_hides_the_entity() -> None:
    scratch = DeviceEntityMapper.empty_option()
    DeviceEntityMapper.map_device(
        [OFFSET, MODE, BEEP], scratch, profile=BrandProfile(setting_entities=LINKS)
    )
    assert scratch["store"]["setting_entities"] == BINDINGS
    keys = {options.get("key") for options in scratch["capabilitiesOptions"].values()}
    assert 11 not in keys and 12 not in keys
    assert 13 in keys


# --- values -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("wanted", "reported"),
    [(21.0, 21.0), (0.1, 0.10000000149011612), (0, 0.0), ("eco", "eco"), (True, True)],
)
def test_matching_values(wanted: Any, reported: Any) -> None:
    assert setting_matches(wanted, reported) is True


@pytest.mark.parametrize(
    ("wanted", "reported"),
    [(21.0, 21.1), ("eco", "boost"), (True, False), ("1", "1.0"), (21.0, None)],
)
def test_differing_values(wanted: Any, reported: Any) -> None:
    assert setting_matches(wanted, reported) is False
