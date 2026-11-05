"""Pure helpers for settings-page fields backed by an ESPHome entity.

A brand driver links a Homey setting to an entity on the setting itself, the
way Z-Wave drivers carry a ``zwave`` object per setting::

    {"id": "temp_offset", "type": "number", ..., "esphome": {"entity": "temp_offset"}}

Kept apart from the runtime sync in this package's ``__init__`` so they can be
imported and tested without a live device, the same way
:mod:`~homey_esphomedriver.capabilities.refresh` is.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from aioesphomeapi import EntityInfo

from homey_esphomedriver.entities.commands.generic import WRITABLE_DOMAINS

_LOGGER = logging.getLogger(__name__)

SETTING_TYPE_DOMAINS: Mapping[str, str] = {
    "number": "number",
    "dropdown": "select",
    "checkbox": "switch",
}
"""Homey setting type to the ESPHome entity domain it can be backed by."""


@dataclass(frozen=True, slots=True)
class SettingEntity:
    """The entity a Homey setting is backed by, as declared in the manifest."""

    object_id: str
    """ESPHome object id the YAML author controls."""

    setting_type: str
    """Homey setting type: ``number``, ``dropdown`` or ``checkbox``."""


def parse_setting_entities(settings: object) -> dict[str, SettingEntity]:
    """Collect ``settings[].esphome.entity`` links from a driver manifest.

    Group children are walked too. A link with no setting id, an unsupported
    setting type, or an entity another setting already claimed is logged and
    left out — two settings writing one entity would fight each other.

    Args:
        settings: The manifest's ``settings`` array.

    Returns:
        Homey setting id to the entity backing it.
    """
    found: dict[str, SettingEntity] = {}
    claimed: dict[str, str] = {}
    for setting in _walk_settings(settings):
        link = setting.get("esphome")
        if not isinstance(link, Mapping) or not link.get("entity"):
            continue
        setting_id = str(setting.get("id") or "")
        object_id = str(link["entity"])
        setting_type = str(setting.get("type") or "")
        if not setting_id:
            _LOGGER.warning("Setting for entity %r has no id; ignored", object_id)
            continue
        if setting_type not in SETTING_TYPE_DOMAINS:
            _LOGGER.warning(
                "Setting %r is a %r field; only %s can be backed by an entity",
                setting_id,
                setting_type,
                ", ".join(SETTING_TYPE_DOMAINS),
            )
            continue
        if object_id in claimed:
            _LOGGER.warning(
                "Setting %r maps to %r, already used by setting %r; ignored",
                setting_id,
                object_id,
                claimed[object_id],
            )
            continue
        claimed[object_id] = setting_id
        found[setting_id] = SettingEntity(object_id, setting_type)
    return found


def _walk_settings(settings: object) -> Iterable[Mapping[str, Any]]:
    if not isinstance(settings, Sequence) or isinstance(settings, (str, bytes)):
        return
    for setting in settings:
        if not isinstance(setting, Mapping):
            continue
        if setting.get("type") == "group":
            yield from _walk_settings(setting.get("children"))
        else:
            yield setting


def writable_domain(entity: EntityInfo) -> str | None:
    """Domain of an entity a setting can write, or ``None``."""
    for domain, writable in WRITABLE_DOMAINS.items():
        if isinstance(entity, writable.info):
            return domain
    return None


def bind_setting_entities(
    entities: Iterable[EntityInfo],
    setting_entities: Mapping[str, SettingEntity],
) -> dict[str, dict[str, Any]]:
    """Resolve each linked setting to the entity key and domain on this node.

    Keys are stored once and reused, like capability options store theirs, so
    bindings are rebuilt wherever entities are listed: pairing, Refresh, and a
    firmware rebuild. A missing entity or one whose domain does not fit the
    setting type is logged and left unbound; the setting then only saves in
    Homey.

    Returns:
        Setting id to ``{"key": int, "domain": str}``, ready for the store.
    """
    by_object_id: dict[str, EntityInfo] = {}
    for entity in entities:
        by_object_id.setdefault(entity.object_id, entity)

    bindings: dict[str, dict[str, Any]] = {}
    for setting_id, target in setting_entities.items():
        entity = by_object_id.get(target.object_id)
        if entity is None:
            _LOGGER.warning(
                "Setting %r maps to entity %r, which this node does not have",
                setting_id,
                target.object_id,
            )
            continue
        domain = writable_domain(entity)
        wanted = SETTING_TYPE_DOMAINS[target.setting_type]
        if domain != wanted:
            _LOGGER.warning(
                "Setting %r is a %s field but entity %r is a %s, not a %s",
                setting_id,
                target.setting_type,
                target.object_id,
                type(entity).__name__,
                wanted,
            )
            continue
        bindings[setting_id] = {"key": entity.key, "domain": domain}
    return bindings
