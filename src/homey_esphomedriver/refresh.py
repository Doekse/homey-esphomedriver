"""Sticky Homey maintenance action that remaps live ESPHome entities."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from homey_esphomedriver.esphome_types import HomeyEspHomeDeviceOption

REFRESH_CAPABILITY = "button.refresh"

REFRESH_CAPABILITY_OPTIONS: dict[str, Any] = json.loads(
    files("homey_esphomedriver")
    .joinpath("homey_template/compose/drivers/templates/esphome-defaults.json")
    .read_text(encoding="utf-8")
)["capabilitiesOptions"][REFRESH_CAPABILITY]


def attach_refresh_capability(homey_device: HomeyEspHomeDeviceOption) -> None:
    """Keep ``button.refresh`` on the pair-time payload after entity mapping."""
    if REFRESH_CAPABILITY not in homey_device["capabilities"]:
        homey_device["capabilities"].append(REFRESH_CAPABILITY)
    homey_device["capabilitiesOptions"][REFRESH_CAPABILITY] = dict(
        REFRESH_CAPABILITY_OPTIONS
    )


def capability_base(capability_id: str) -> str:
    """Homey type of a capability, ignoring any object-id suffix."""
    return capability_id.split(".", 1)[0]


def allocate_capability_id(scratch_id: str, key: int, taken: set[str]) -> str:
    """Pick a Homey id for a new mapping that does not collide with ``taken``."""
    if scratch_id not in taken:
        return scratch_id
    return f"{capability_base(scratch_id)}.{key}"


def plan_capability_refresh(
    current_options: dict[str, dict[str, Any]],
    desired_options: dict[str, dict[str, Any]],
) -> tuple[
    list[str],
    list[tuple[str, dict[str, Any]]],
    list[tuple[str, dict[str, Any]]],
]:
    """Diff current vs remapped caps by ``(entity key, capability base)``.

    Returns ``(remove_ids, add_items, update_items)``. Unchanged mappings keep
    their current Homey ids so bare-id assignment cannot reshuffle Flows.
    Caps without a ``key`` are left alone.
    """
    desired = {
        (int(options["key"]), capability_base(capability_id)): (
            capability_id,
            options,
        )
        for capability_id, options in desired_options.items()
        if options.get("key") is not None
    }

    to_remove: list[str] = []
    to_update: list[tuple[str, dict[str, Any]]] = []
    matched: set[tuple[int, str]] = set()
    taken: set[str] = set()

    for capability_id, options in current_options.items():
        key = options.get("key")
        if key is None:
            taken.add(capability_id)
            continue
        identity = (int(key), capability_base(capability_id))
        match = desired.get(identity)
        if match is None:
            to_remove.append(capability_id)
            continue
        taken.add(capability_id)
        matched.add(identity)
        merged = {**options, **match[1]}
        if merged != options:
            to_update.append((capability_id, merged))

    to_add: list[tuple[str, dict[str, Any]]] = []
    for identity, (scratch_id, options) in desired.items():
        if identity in matched:
            continue
        new_id = allocate_capability_id(scratch_id, identity[0], taken)
        taken.add(new_id)
        to_add.append((new_id, options))

    return to_remove, to_add, to_update
