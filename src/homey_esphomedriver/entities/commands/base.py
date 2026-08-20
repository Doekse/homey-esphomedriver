"""Shared helpers for Homey capability → Native API commands."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from homey_esphomedriver.esphome_client import EspHomeClient
    from homey_esphomedriver.esphome_device import EspHomeDevice


class AbstractEntityCommandHandler:
    """Base with entity-key helpers used by concrete command handlers."""

    CAPABILITIES: ClassVar[tuple[str, ...]] = ()
    VALUELESS_CAPABILITIES: ClassVar[tuple[str, ...]] = ()
    MULTI_CAPABILITIES: ClassVar[tuple[tuple[tuple[str, ...], str], ...]] = ()
    ENTITY_TYPE: ClassVar[str | None] = None
    REQUIRE_ENTITY_TYPE: ClassVar[bool] = False

    def __init__(self, device: EspHomeDevice) -> None:
        self.device = device

    def _require_client(self) -> EspHomeClient:
        """Return the live Native API session."""
        return self.device._require_client()

    def _get_entity_key(self, capability_id: str) -> int:
        """Return the ESPHome entity key stored on the capability at pair time."""
        return int(self.device.get_capability_options(capability_id)["key"])

    def _get_entity_type(self, capability_id: str) -> str | None:
        """Return the pair-time entity domain, or ``None`` if unset."""
        entity_type = self.device.get_capability_options(capability_id).get(
            "entity_type"
        )
        return str(entity_type) if entity_type is not None else None
