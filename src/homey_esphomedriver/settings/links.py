"""Pure helpers for settings-page fields backed by an ESPHome entity.

A brand driver links a Homey setting to an entity on the setting itself, so
the two cannot drift apart::

    {"id": "temp_offset", "type": "number", ...,
     "esphome": {"domain": "number", "name": "Temperature offset"}}

Kept apart from the runtime sync in this package's ``__init__`` so they can be
imported and tested without a live device.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass

from homey_esphomedriver.esphome_util import walk_settings

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

    domain: str
    """ESPHome domain: ``number``, ``select`` or ``switch``."""

    name: str
    """Entity name the YAML author chose."""

    device_id: int = 0
    """Sub-device the entity belongs to; 0 is the node itself."""

    @property
    def ref(self) -> tuple[str, str, int]:
        """``(domain, name, device_id)``, as capability bindings name entities."""
        return (self.domain, self.name, self.device_id)


def parse_setting_entities(settings: object) -> dict[str, SettingEntity]:
    """Collect ``settings[].esphome`` links from a driver manifest.

    Group children are walked too. ``domain`` may be left out; it follows from
    the setting type. A link with no setting id, an unsupported setting type,
    a domain that does not fit the type, or an entity another setting already
    claimed is logged and left out: two settings writing one entity would
    fight each other.

    Args:
        settings: The manifest's ``settings`` array.

    Returns:
        Homey setting id to the entity backing it.
    """
    found: dict[str, SettingEntity] = {}
    claimed: dict[tuple[str, str, int], str] = {}
    for setting in walk_settings(settings):
        link = setting.get("esphome")
        if not isinstance(link, Mapping):
            continue
        setting_id = str(setting.get("id") or "")
        if "entity" in link and "name" not in link:
            _LOGGER.warning(
                "Setting %r links entity %r by object id; link it by name instead: "
                '"esphome": {"domain": "...", "name": "..."}',
                setting_id,
                link["entity"],
            )
            continue
        name = link.get("name")
        if not isinstance(name, str):
            continue
        setting_type = str(setting.get("type") or "")
        if not setting_id:
            _LOGGER.warning("Setting for entity %r has no id; ignored", name)
            continue
        wanted = SETTING_TYPE_DOMAINS.get(setting_type)
        if wanted is None:
            _LOGGER.warning(
                "Setting %r is a %r field; only %s can be backed by an entity",
                setting_id,
                setting_type,
                ", ".join(SETTING_TYPE_DOMAINS),
            )
            continue
        domain = str(link.get("domain") or wanted)
        if domain != wanted:
            _LOGGER.warning(
                "Setting %r is a %s field, which a %s entity backs, not a %s",
                setting_id,
                setting_type,
                wanted,
                domain,
            )
            continue
        target = SettingEntity(domain, name, int(link.get("device_id") or 0))
        if target.ref in claimed:
            _LOGGER.warning(
                "Setting %r maps to %s %r, already used by setting %r; ignored",
                setting_id,
                domain,
                name,
                claimed[target.ref],
            )
            continue
        claimed[target.ref] = setting_id
        found[setting_id] = target
    return found
