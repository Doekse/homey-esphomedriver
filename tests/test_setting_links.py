"""Linking a Homey setting to the ESPHome entity behind it.

A brand driver links a setting to an entity on the setting itself
(``settings[].esphome``). These tests pin how a manifest link is parsed.
"""

from __future__ import annotations

import logging

import pytest

from homey_esphomedriver.profile import BrandProfile
from homey_esphomedriver.settings.links import (
    SettingEntity,
    parse_setting_entities,
)

LINKS = {
    "offset": SettingEntity("number", "Temperature offset"),
    "mode": SettingEntity("select", "Mode"),
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
                    "esphome": {"domain": "number", "name": "Temperature offset"},
                },
                {
                    "type": "group",
                    "children": [
                        {
                            "id": "mode",
                            "type": "dropdown",
                            "esphome": {"domain": "select", "name": "Mode"},
                        }
                    ],
                },
            ]
        }
    )
    assert profile.setting_entities == LINKS


def test_domain_follows_from_the_setting_type() -> None:
    links = parse_setting_entities(
        [{"id": "beep", "type": "checkbox", "esphome": {"name": "Beep"}}]
    )
    assert links == {"beep": SettingEntity("switch", "Beep")}


def test_sub_device_is_part_of_the_link() -> None:
    links = parse_setting_entities(
        [
            {
                "id": "offset",
                "type": "number",
                "esphome": {"name": "Offset", "device_id": 3},
            }
        ]
    )
    assert links["offset"].ref == ("number", "Offset", 3)


def test_esphome_object_and_setting_links_combine() -> None:
    profile = BrandProfile.from_manifest(
        {
            "esphome": {"projects": ["acme.air"]},
            "settings": [
                {
                    "id": "offset",
                    "type": "number",
                    "esphome": {"name": "Temperature offset"},
                }
            ],
        }
    )
    assert profile.projects == frozenset({"acme.air"})
    assert profile.setting_entities == {"offset": LINKS["offset"]}


def test_unsupported_type_wrong_domain_and_duplicate_entity_are_ignored() -> None:
    links = parse_setting_entities(
        [
            {"id": "label", "type": "text", "esphome": {"name": "Offset"}},
            {"id": "first", "type": "number", "esphome": {"name": "Offset"}},
            {"id": "second", "type": "number", "esphome": {"name": "Offset"}},
            {
                "id": "wrong",
                "type": "number",
                "esphome": {"domain": "select", "name": "X"},
            },
            {"type": "number", "esphome": {"name": "Other"}},
        ]
    )
    assert links == {"first": SettingEntity("number", "Offset")}


def test_object_id_link_is_rejected_with_a_hint(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="homey_esphomedriver.settings.links"):
        links = parse_setting_entities(
            [{"id": "offset", "type": "number", "esphome": {"entity": "temp_offset"}}]
        )
    assert links == {}
    assert "by name" in caplog.text
