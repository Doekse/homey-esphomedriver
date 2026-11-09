"""Which ESPHome nodes a Homey driver takes, read from its manifest.

Brand apps declare an ``esphome`` object in ``driver.compose.json``.
:class:`EspHomeDriver` reads it from ``self.manifest``. Which capabilities a
device has is the driver's own ``capabilities`` list, bound to entities with
:meth:`EspHomeDevice.register_capability`.

The generic esphome-homey app (``io.esphome``) omits ``projects`` so every
project is accepted. Brand apps that ship one driver per SKU set ``projects``
(exact ESPHome ``project.name``); brand-wide or multi-variant drivers can use
``projectPrefix``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from homey_esphomedriver.settings.links import SettingEntity, parse_setting_entities

_LOGGER = logging.getLogger(__name__)

COMPOSE_KEYS = frozenset(
    {
        "clientInfo",
        "projects",
        "projectPrefix",
        "nativeApps",
    }
)
"""Keys of the ``driver.compose.json`` ``esphome`` object."""

DEFAULT_CLIENT_INFO = "Homey ESPHome"
"""Identifies the generic Homey ESPHome app on the node's API hello."""


@dataclass(frozen=True, slots=True)
class BrandProfile:
    """Product filters consulted at pair and connect time.

    Built from the driver manifest ``esphome`` object.
    """

    client_info: str = DEFAULT_CLIENT_INFO
    """Name shown on the node for this Homey client."""

    projects: frozenset[str] | None = None
    """Exact ESPHome ``project.name`` values this driver accepts."""

    project_prefix: tuple[str, ...] | None = None
    """Prefixes matched with ``startswith``.

    ``None`` with :attr:`projects` unset accepts every project.
    """

    native_apps: Mapping[str, str] = field(default_factory=dict)
    """ESPHome ``project.name`` to Homey App Store name (``io.esphome`` only)."""

    setting_entities: Mapping[str, SettingEntity] = field(default_factory=dict)
    """Homey setting id to the entity backing it.

    Filled by :meth:`from_manifest` from ``settings[].esphome``, so the link
    sits on the setting it configures. The entity is written when the user
    saves the setting, and the setting follows what the node reports.
    """

    @classmethod
    def from_manifest(cls, manifest: Mapping[str, Any] | None) -> BrandProfile:
        """Build a profile from a Homey driver manifest's ``esphome`` object.

        Args:
            manifest: Driver manifest, typically ``self.manifest``.

        Returns:
            A profile with the ``settings[].esphome`` links; one that accepts
            every project when ``esphome`` is missing.
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
            native_apps=_string_map(data.get("nativeApps")),
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
