"""Sticky Homey ids when remapping a live device onto a new pair-time payload."""

from __future__ import annotations

from typing import Any


def capability_base(capability_id: str) -> str:
    """Homey type of a capability, ignoring any object-id suffix."""
    return capability_id.split(".", 1)[0]


def plan_capability_refresh(
    current_options: dict[str, dict[str, Any]],
    desired_options: dict[str, dict[str, Any]],
) -> tuple[
    list[str],
    list[tuple[str, dict[str, Any]]],
    list[tuple[str, dict[str, Any]]],
]:
    """Diff current vs the pair-time payload, keeping sticky Homey ids.

    Entity-backed caps keep the current Homey id when ``(key, capability
    base)`` matches. Caps without a ``key``, including stored ``None``, match
    on Homey id.
    """
    desired_keyed = {
        (int(options["key"]), capability_base(capability_id)): (
            capability_id,
            options,
        )
        for capability_id, options in desired_options.items()
        if options and options.get("key") is not None
    }

    to_remove: list[str] = []
    to_add: list[tuple[str, dict[str, Any]]] = []
    to_update: list[tuple[str, dict[str, Any]]] = []
    matched: set[tuple[int, str]] = set()
    taken: set[str] = set()

    for capability_id, stored in current_options.items():
        # WORKAROUND: Homey may persist options as null (Athom will return {}).
        options = stored or {}
        key = options.get("key")
        if key is None:
            desired = desired_options.get(capability_id)
            if desired is None:
                to_remove.append(capability_id)
                continue
            taken.add(capability_id)
            merged = {**options, **desired}
            if merged != options:
                to_update.append((capability_id, merged))
            continue

        identity = (int(key), capability_base(capability_id))
        match = desired_keyed.get(identity)
        if match is None:
            to_remove.append(capability_id)
            continue
        taken.add(capability_id)
        matched.add(identity)
        merged = {**options, **match[1]}
        if merged != options:
            to_update.append((capability_id, merged))

    for capability_id, options in desired_options.items():
        key = options.get("key")
        if key is None:
            if capability_id not in current_options:
                to_add.append((capability_id, options))
                taken.add(capability_id)
            continue
        identity = (int(key), capability_base(capability_id))
        if identity in matched:
            continue
        new_id = (
            capability_id
            if capability_id not in taken
            else f"{capability_base(capability_id)}.{int(key)}"
        )
        taken.add(new_id)
        to_add.append((new_id, options))

    return to_remove, to_add, to_update
