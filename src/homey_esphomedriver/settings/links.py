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
