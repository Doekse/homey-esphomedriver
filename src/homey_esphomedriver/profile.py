"""Brand-specific filters and remaps for a Homey ESPHome driver.

Brand apps declare an ``esphome`` object in ``driver.compose.json``.
:class:`EspHomeDriver` reads it from ``self.manifest``; compose is the only
source of profile data. For a Python hook such as ``after_map``, subclass
:class:`BrandProfile` and set it as the driver's ``brand_profile_class``.

The generic esphome-homey app (``io.esphome``) omits ``projects`` so every
project is accepted. Brand apps that ship one driver per SKU set ``projects``
(exact ESPHome ``project.name``); brand-wide or multi-variant drivers can use
``projectPrefix``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from fnmatch import fnmatchcase
from typing import Any

from aioesphomeapi import EntityInfo

from homey_esphomedriver.esphome_types import HomeyEspHomeDeviceOption
from homey_esphomedriver.settings.links import SettingEntity, parse_setting_entities


def _is_pattern(entry: str) -> bool:
    """Whether a ``hiddenEntities`` entry is a pattern rather than an id.

    ESPHome object ids are slugified to ``[a-z0-9_-]``, so these characters
    cannot appear in a literal id and are unambiguous as wildcards.
    """
    return any(ch in entry for ch in "*?[")


_LOGGER = logging.getLogger(__name__)

COMPOSE_KEYS = frozenset(
    {
        "clientInfo",
        "projects",
        "projectPrefix",
        "hiddenEntities",
        "deviceEntities",
        "deviceClassOverrides",
        "nativeApps",
        "capabilityOverrides",
    }
)
"""Keys of the ``driver.compose.json`` ``esphome`` object."""

DEFAULT_CLIENT_INFO = "Homey ESPHome"
"""Identifies the generic Homey ESPHome app on the node's API hello."""


@dataclass(frozen=True, slots=True)
class BrandProfile:
    """
    Override surface consulted at pair, map, and connect time.

    Built from the driver manifest ``esphome`` object. Subclass it and set
    the subclass as the driver's ``brand_profile_class`` to override
    :meth:`after_map` or :meth:`device_class_for`.
    """

    client_info: str = DEFAULT_CLIENT_INFO
    """Name shown on the node for this Homey client."""

    projects: frozenset[str] | None = None
    """Exact ESPHome ``project.name`` values this driver accepts."""

    project_prefix: tuple[str, ...] | None = None
    """Prefixes matched with ``startswith``.

    ``None`` with :attr:`projects` unset accepts every project.
    """

    hidden_entities: frozenset[str] = field(default_factory=frozenset)
    """Entity object ids to omit, on top of diagnostic/config defaults.

    An entry containing ``*``, ``?`` or ``[`` is a shell-style pattern rather
    than an id, so a family of entities can be named once: ``debug_*`` hides
    every debug helper a node exposes, and stays correct when the node gains
    another one.
    """

    device_entities: Mapping[str, str] = field(default_factory=dict)
    """Entity object id to Homey capability id."""

    device_class_overrides: Mapping[str, str] = field(default_factory=dict)
    """Entity object id to Homey device class."""

    native_apps: Mapping[str, str] = field(default_factory=dict)
    """ESPHome ``project.name`` to Homey App Store name (``io.esphome`` only)."""

    capability_overrides: Mapping[tuple[str, str], str] = field(default_factory=dict)
    """``(object_id, default_capability_id)`` to capability id."""

    setting_entities: Mapping[str, SettingEntity] = field(default_factory=dict)
    """Homey setting id to the entity backing it.

    Read from ``settings[].esphome.entity`` in the driver manifest rather than
    the ``esphome`` object, so the link sits on the setting it configures. The
    entity is written when the user saves the setting, and the setting follows
    what the node reports. A mapped entity is left off the device tile.
    """

    @classmethod
    def from_manifest(cls, manifest: Mapping[str, Any] | None) -> BrandProfile:
        """Build a profile from a Homey driver manifest's ``esphome`` object.

        Args:
            manifest: Driver manifest, typically ``self.manifest``.

        Returns:
            A profile of this class, with the ``settings[].esphome.entity``
            links; one with no filters or remaps when ``esphome`` is missing,
            so a subclass keeps its hooks.
        """
        raw = manifest.get("esphome") if manifest else None
        profile = cls.from_compose(raw) if isinstance(raw, Mapping) else cls()
        setting_entities = parse_setting_entities(
            manifest.get("settings") if manifest else None
        )
        if not setting_entities:
            return profile
        return profile.replace(setting_entities=setting_entities)

    @classmethod
    def from_compose(cls, data: Mapping[str, Any]) -> BrandProfile:
        """Build a profile from a ``driver.compose.json`` ``esphome`` object.

        Args:
            data: The ``esphome`` object. Keys are listed in
                :data:`COMPOSE_KEYS`; any other key is logged and ignored.
        """
        unknown = sorted(set(data) - COMPOSE_KEYS)
        if unknown:
            _LOGGER.warning(
                "Ignoring unknown esphome compose key(s) %s; expected one of %s",
                ", ".join(map(str, unknown)),
                ", ".join(sorted(COMPOSE_KEYS)),
            )
        return cls(
            client_info=str(data.get("clientInfo") or DEFAULT_CLIENT_INFO),
            projects=_optional_names(data.get("projects")),
            project_prefix=_optional_tuple(data.get("projectPrefix")),
            hidden_entities=frozenset(_string_list(data.get("hiddenEntities"))),
            device_entities=_string_map(data.get("deviceEntities")),
            device_class_overrides=_string_map(data.get("deviceClassOverrides")),
            native_apps=_string_map(data.get("nativeApps")),
            capability_overrides=_capability_overrides(data.get("capabilityOverrides")),
        )

    def replace(self, **kwargs: object) -> BrandProfile:
        """Return a copy with the given fields overridden."""
        return replace(self, **kwargs)

    def accepts_project(self, project_name: str) -> bool:
        """Return whether this driver should pair or drive the given project.

        Args:
            project_name: ESPHome firmware ``project.name``.
        """
        names = self.projects
        prefixes = self.project_prefix
        if names is None and prefixes is None:
            return True
        if names is not None and project_name in names:
            return True
        if prefixes is not None and any(
            project_name.startswith(prefix) for prefix in prefixes
        ):
            return True
        return False

    def accepts_discovery(self, txt: Mapping[str, str]) -> bool:
        """Return whether mDNS TXT ``project_name`` is allowed for this driver."""
        if self.projects is None and self.project_prefix is None:
            return True
        return self.accepts_project(txt.get("project_name") or "")

    def native_app_suggestion(self, project_name: str) -> str | None:
        """Return a Homey App Store name when a dedicated app exists."""
        return self.native_apps.get(project_name)

    def skip_entity(self, entity: EntityInfo) -> bool:
        """Return whether the brand wants this entity omitted from the Homey device."""
        object_id = entity.object_id
        if object_id in self.hidden_entities:
            return True
        # The settings page is a mapped entity's one writer; a tile control
        # beside it would be a second path to the same value.
        if any(
            target.object_id == object_id for target in self.setting_entities.values()
        ):
            return True
        return any(
            _is_pattern(entry) and fnmatchcase(object_id, entry)
            for entry in self.hidden_entities
        )

    def capability_id_for(self, entity: EntityInfo, default: str) -> str:
        """Return a remapped capability id, or ``default`` when unset."""
        pair = self.capability_overrides.get((entity.object_id, default))
        if pair is not None:
            return pair
        return self.device_entities.get(entity.object_id, default)

    def device_class_for(
        self,
        homey_device: HomeyEspHomeDeviceOption,
        entity: EntityInfo | None,
    ) -> str | None:
        """Return a Homey class override for ``entity``.

        Args:
            homey_device: Mapped device so subclasses can inspect already-added
                capabilities. Unused by the default implementation.
            entity: Entity currently being mapped.

        Returns:
            Override class, or ``None`` to keep the mapper default.
        """
        del homey_device
        if entity is None:
            return None
        return self.device_class_overrides.get(entity.object_id)

    def after_map(
        self,
        entities: Sequence[EntityInfo],
        homey_device: HomeyEspHomeDeviceOption,
    ) -> None:
        """Hook after all entities are mapped.

        Override on a subclass set as the driver's ``brand_profile_class``
        for brand-specific post-processing. The default is a no-op.
        """
        del entities, homey_device


DEFAULT_BRAND_PROFILE = BrandProfile()
"""Profile that accepts every project and applies no remaps."""


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [str(item) for item in value]
    return []


def _optional_names(raw: object) -> frozenset[str] | None:
    if raw is None:
        return None
    return frozenset(_string_list(raw))


def _optional_tuple(raw: object) -> tuple[str, ...] | None:
    if raw is None:
        return None
    return tuple(_string_list(raw))


def _string_map(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _capability_overrides(value: object) -> dict[tuple[str, str], str]:
    if not isinstance(value, Mapping):
        return {}
    parsed: dict[tuple[str, str], str] = {}
    for object_id, mapping in value.items():
        if not isinstance(mapping, Mapping):
            continue
        for default, capability_id in mapping.items():
            parsed[(str(object_id), str(default))] = str(capability_id)
    return parsed
