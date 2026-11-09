"""Which ESPHome nodes a Homey driver takes, read from its manifest.

Brand apps declare an ``esphome`` object in ``driver.compose.json``.
:class:`EspHomeDriver` reads it from ``self.manifest``; a class-level
``brand_profile`` on the driver still wins when set. Which capabilities a
device has is the driver's own ``capabilities`` list, bound to entities with
:meth:`EspHomeDevice.register_capability`.

The generic esphome-homey app (``io.esphome``) omits ``projects`` so every
project is accepted. Brand apps that ship one driver per SKU set ``projects``
(exact ESPHome ``project.name``); brand-wide or multi-variant drivers can use
``projectPrefix``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

DEFAULT_CLIENT_INFO = "Homey ESPHome"
"""Identifies the generic Homey ESPHome app on the node's API hello."""


@dataclass(frozen=True, slots=True)
class BrandProfile:
    """Product filters consulted at pair and connect time.

    Built from the driver manifest ``esphome`` object, or assigned as a
    class-level ``brand_profile`` on the driver.
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

    @classmethod
    def from_manifest(cls, manifest: Mapping[str, Any] | None) -> BrandProfile:
        """Build a profile from a Homey driver manifest's ``esphome`` object.

        Args:
            manifest: Driver manifest, typically ``self.manifest``.

        Returns:
            A profile that accepts every project when ``esphome`` is missing.
        """
        raw = manifest.get("esphome") if manifest else None
        if not isinstance(raw, Mapping):
            return cls()
        return cls.from_compose(raw)

    @classmethod
    def from_compose(cls, data: Mapping[str, Any]) -> BrandProfile:
        """Build a profile from a ``driver.compose.json`` ``esphome`` object.

        Args:
            data: The ``esphome`` object. CamelCase compose keys are preferred;
                snake_case and a few legacy aliases are also accepted.
        """
        return cls(
            client_info=str(
                _pick(data, "clientInfo", "client_info") or DEFAULT_CLIENT_INFO
            ),
            projects=_optional_names(data, "projects", "projectNames", "project_names"),
            project_prefix=_optional_tuple(
                data,
                "projectPrefix",
                "projectPrefixes",
                "project_prefix",
                "project_prefixes",
            ),
            native_apps=_string_map(_pick(data, "nativeApps", "native_apps") or {}),
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


def _pick(data: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [str(item) for item in value]
    return []


def _optional_names(data: Mapping[str, Any], *keys: str) -> frozenset[str] | None:
    raw = _pick(data, *keys)
    if raw is None:
        return None
    return frozenset(_string_list(raw))


def _optional_tuple(data: Mapping[str, Any], *keys: str) -> tuple[str, ...] | None:
    raw = _pick(data, *keys)
    if raw is None:
        return None
    return tuple(_string_list(raw))


def _string_map(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items()}
