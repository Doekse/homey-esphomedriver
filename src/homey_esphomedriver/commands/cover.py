"""Homey windowcovering / garage capabilities → ESPHome ``cover_command``."""

from __future__ import annotations

from typing import Any

from homey_esphomedriver.commands.base import AbstractEntityCommandHandler


class CoverCommandHandler(AbstractEntityCommandHandler):
    CAPABILITIES = (
        "windowcoverings_state",
        "windowcoverings_set",
        "windowcoverings_tilt_set",
        "windowcoverings_tilt_up",
        "windowcoverings_tilt_down",
        "garagedoor_closed",
    )
    ENTITY_TYPE = "cover"

    async def windowcoverings_state(
        self,
        value: Any,
        capability_id: str = "windowcoverings_state",
        **_kwargs: Any,
    ) -> None:
        key = self._get_entity_key(capability_id)
        client = self._require_client()
        match value:
            case "up":
                client.command("cover_command", key, position=1.0)
            case "down":
                client.command("cover_command", key, position=0.0)
            case _:
                client.command("cover_command", key, stop=True)

    async def windowcoverings_set(
        self,
        value: Any,
        capability_id: str = "windowcoverings_set",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "cover_command",
            self._get_entity_key(capability_id),
            position=float(value),
        )

    async def windowcoverings_tilt_set(
        self,
        value: Any,
        capability_id: str = "windowcoverings_tilt_set",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "cover_command",
            self._get_entity_key(capability_id),
            tilt=float(value),
        )

    async def windowcoverings_tilt_up(
        self,
        _value: Any = True,
        capability_id: str = "windowcoverings_tilt_up",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "cover_command",
            self._get_entity_key(capability_id),
            tilt=1.0,
        )

    async def windowcoverings_tilt_down(
        self,
        _value: Any = True,
        capability_id: str = "windowcoverings_tilt_down",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "cover_command",
            self._get_entity_key(capability_id),
            tilt=0.0,
        )

    async def garagedoor_closed(
        self,
        value: Any,
        capability_id: str = "garagedoor_closed",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "cover_command",
            self._get_entity_key(capability_id),
            position=0.0 if value else 1.0,
        )
