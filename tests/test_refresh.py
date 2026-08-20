"""Refresh-capability planning tests.

``plan_capability_refresh`` diffs by ``(entity key, capability base)`` so
remapping cannot reshuffle Flow cards bound to bare Homey ids. Caps without a
``key`` (the refresh button) are left alone.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from homey_esphomedriver.esphome_types import HomeyEspHomeDeviceOption
from homey_esphomedriver.refresh import (
    REFRESH_CAPABILITY,
    REFRESH_CAPABILITY_OPTIONS,
    allocate_capability_id,
    attach_refresh_capability,
    capability_base,
    plan_capability_refresh,
)


def device() -> HomeyEspHomeDeviceOption:
    return cast(
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


@pytest.mark.parametrize(
    ("capability_id", "expected"),
    [
        ("onoff", "onoff"),
        ("measure_temperature.1", "measure_temperature"),
        ("esphome_number.pump", "esphome_number"),
    ],
)
def test_capability_base(capability_id: str, expected: str) -> None:
    assert capability_base(capability_id) == expected


def test_allocate_capability_id_keeps_scratch_when_free() -> None:
    assert allocate_capability_id("onoff", 7, set()) == "onoff"


def test_allocate_capability_id_indexes_on_collision() -> None:
    assert allocate_capability_id("onoff", 7, {"onoff"}) == "onoff.7"


def test_attach_refresh_capability_appends_once() -> None:
    homey_device = device()
    attach_refresh_capability(homey_device)
    attach_refresh_capability(homey_device)
    assert homey_device["capabilities"] == [REFRESH_CAPABILITY]
    assert (
        homey_device["capabilitiesOptions"][REFRESH_CAPABILITY]
        == REFRESH_CAPABILITY_OPTIONS
    )


def test_plan_keeps_current_id_when_identity_matches() -> None:
    """Matched (key, base) pairs keep the current Homey id, not the scratch id."""
    current = {"onoff": {"key": 1, "title": "Relay"}}
    desired = {"onoff.relay": {"key": 1, "title": "Relay"}}
    to_remove, to_add, to_update = plan_capability_refresh(current, desired)
    assert to_remove == []
    assert to_add == []
    assert to_update == []


def test_plan_updates_when_options_change() -> None:
    current = {"onoff": {"key": 1, "title": "Old"}}
    desired = {"onoff": {"key": 1, "title": "New"}}
    to_remove, to_add, to_update = plan_capability_refresh(current, desired)
    assert to_remove == []
    assert to_add == []
    assert to_update == [("onoff", {"key": 1, "title": "New"})]


def test_plan_removes_gone_entities_and_adds_new_ones() -> None:
    current = {"onoff": {"key": 1}, "measure_temperature": {"key": 2}}
    desired = {"measure_temperature": {"key": 2}, "onoff.pump": {"key": 3}}
    to_remove, to_add, to_update = plan_capability_refresh(current, desired)
    assert to_remove == ["onoff"]
    assert to_update == []
    assert to_add == [("onoff.pump", {"key": 3})]


def test_plan_indexes_scratch_when_bare_id_already_taken() -> None:
    """A new entity whose scratch id is already taken gets ``base.key``."""
    current = {"onoff": {"key": 1}}
    desired: dict[str, dict[str, Any]] = {
        "onoff.relay": {"key": 1},
        "onoff": {"key": 2},
    }
    to_remove, to_add, to_update = plan_capability_refresh(current, desired)
    assert to_remove == []
    assert to_update == []
    assert to_add == [("onoff.2", {"key": 2})]


def test_plan_leaves_keyless_capabilities_alone() -> None:
    """The refresh button has no entity key and must not be removed or remapped."""
    current = {
        REFRESH_CAPABILITY: {"title": "Refresh"},
        "onoff": {"key": 1},
    }
    desired = {"onoff": {"key": 1}}
    to_remove, to_add, to_update = plan_capability_refresh(current, desired)
    assert to_remove == []
    assert to_add == []
    assert to_update == []
