"""Linking a Homey setting to the ESPHome entity behind it.

A brand driver links a setting to an entity on the setting itself
(``settings[].esphome.entity``), the way Z-Wave drivers put ``zwave`` on each
setting. These tests pin how a manifest link is parsed and how it is bound to
an entity key on the node.
"""

from __future__ import annotations

from aioesphomeapi import NumberInfo, SelectInfo, SensorInfo, SwitchInfo

from homey_esphomedriver.entities.mapping import DeviceEntityMapper
from homey_esphomedriver.profile import BrandProfile
from homey_esphomedriver.settings.links import (
    SettingEntity,
    bind_setting_entities,
    parse_setting_entities,
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
    assert bind_setting_entities([OFFSET, reading], links) == {}


def test_pairing_stores_bindings_and_hides_the_entity() -> None:
    scratch = DeviceEntityMapper.empty_option()
    DeviceEntityMapper.map_device(
        [OFFSET, MODE, BEEP], scratch, profile=BrandProfile(setting_entities=LINKS)
    )
    assert scratch["store"]["setting_entities"] == BINDINGS
    keys = {options.get("key") for options in scratch["capabilitiesOptions"].values()}
    assert 11 not in keys and 12 not in keys
    assert 13 in keys
