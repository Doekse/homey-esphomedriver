"""Shared helpers for Homey capability → Native API commands."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar, Protocol


class _EntityCommander(Protocol):
    """Device surface needed by entity command handlers."""

    def command(self, name: str, *args: Any, **kwargs: Any) -> None:
        """Forward a Native API command once the session is ready."""
        ...

    def get_capability_options(self, capability_id: str) -> Mapping[str, Any]:
        """Return pair-time options for ``capability_id``."""
        ...

    def has_capability(self, capability_id: str) -> bool:
        """Return whether the device currently has ``capability_id``."""
        ...

    def get_capability_value(self, capability_id: str) -> Any:
        """Return the current Homey value for ``capability_id``."""
        ...

    async def set_capability_value(self, capability_id: str, value: Any) -> None:
        """Write a Homey capability value."""
        ...

    async def trigger_capability_listener(
        self,
        capability_id: str,
        value: Any,
        **kwargs: Any,
    ) -> None:
        """Run the registered listener for ``capability_id`` and update its value."""
        ...

    def error(self, *args: Any) -> None:
        """Log an error."""
        ...


class AbstractEntityCommandHandler:
    """Base with entity-key helpers used by concrete command handlers.

    Subclasses declare ownership via class-level metadata so the device
    orchestrator can build its registry and wire Homey capability listeners.
    """

    CAPABILITIES: ClassVar[tuple[str, ...]] = ()
    MULTI_CAPABILITIES: ClassVar[tuple[tuple[str, ...], ...]] = ()
    ENTITY_TYPE: ClassVar[str | None] = None

    def __init__(self, device: _EntityCommander) -> None:
        self.device = device

    def _require_client(self) -> _EntityCommander:
        """Return the device for Native API commands (session gated by ``command``)."""
        return self.device

    def _get_entity_key(self, capability_id: str) -> int:
        """Return the ESPHome entity key stored on the capability at pair time."""
        return int(self.device.get_capability_options(capability_id)["key"])

    def _get_entity_type(self, capability_id: str) -> str | None:
        """Return the pair-time entity domain, or ``None`` if unset."""
        entity_type = self.device.get_capability_options(capability_id).get(
            "entity_type"
        )
        return str(entity_type) if entity_type is not None else None
