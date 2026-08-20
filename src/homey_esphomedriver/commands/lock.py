"""Homey lock capabilities → ESPHome ``lock_command``."""

from __future__ import annotations

from typing import Any

from aioesphomeapi import LockCommand

from homey_esphomedriver.commands.base import AbstractEntityCommandHandler


class LockEntityCommandHandler(AbstractEntityCommandHandler):
    CAPABILITIES = ("locked", "open")
    VALUELESS_CAPABILITIES = ("open",)
    ENTITY_TYPE = "lock"
    REQUIRE_ENTITY_TYPE = True

    async def locked(
        self,
        value: Any,
        capability_id: str = "locked",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "lock_command",
            self._get_entity_key(capability_id),
            LockCommand.LOCK if value else LockCommand.UNLOCK,
        )

    async def open(
        self,
        *,
        capability_id: str,
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "lock_command",
            self._get_entity_key(capability_id),
            LockCommand.OPEN,
        )
