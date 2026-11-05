"""Multi-domain onoff plus button / number / select command handlers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from aioesphomeapi import (
    ClimateMode,
    EntityInfo,
    NumberInfo,
    SelectInfo,
    SwitchInfo,
)

from homey_esphomedriver.entities.commands.base import AbstractEntityCommandHandler

if TYPE_CHECKING:
    from homey_esphomedriver.esphome_client import EspHomeClient


@dataclass(frozen=True, slots=True)
class WritableDomain:
    """An ESPHome entity domain Homey writes values to."""

    info: type[EntityInfo]
    """Entity info type that identifies an entity of this domain."""

    command: str
    """Native API client method that writes an entity of this domain."""

    coerce: Callable[[Any], Any]
    """Turns a Homey value into what :attr:`command` takes."""


WRITABLE_DOMAINS: Mapping[str, WritableDomain] = {
    "number": WritableDomain(info=NumberInfo, command="number_command", coerce=float),
    "select": WritableDomain(info=SelectInfo, command="select_command", coerce=str),
    "switch": WritableDomain(info=SwitchInfo, command="switch_command", coerce=bool),
}
"""The entity domains Homey writes, by domain name.

The one table for these domains: the capability listeners and settings-page
fields backed by an entity both write through it, so they cannot drift.
"""


def write_entity_value(
    client: EspHomeClient, domain: str, key: int, value: Any
) -> None:
    """Send ``value`` to the entity ``key`` of ``domain``.

    Raises:
        KeyError: If Homey does not write entities of ``domain``.
        TypeError, ValueError: If the value cannot be coerced for the domain.
    """
    writable = WRITABLE_DOMAINS[domain]
    client.command(writable.command, key, writable.coerce(value))


class GenericEntityCommandHandler(AbstractEntityCommandHandler):
    CAPABILITIES = ("onoff", "button", "number", "select")
    VALUELESS_CAPABILITIES = ("button",)

    async def onoff(
        self,
        value: Any,
        capability_id: str = "onoff",
        **_kwargs: Any,
    ) -> None:
        key = self._get_entity_key(capability_id)
        entity_type = self._get_entity_type(capability_id)
        client = self._require_client()

        if entity_type == "light":
            client.command("light_command", key, state=bool(value))
            return
        if entity_type == "fan":
            client.command("fan_command", key, state=bool(value))
            return
        if entity_type == "valve":
            client.command("valve_command", key, position=1.0 if value else 0.0)
            return
        if entity_type == "climate":
            if value:
                client.command(
                    "climate_command",
                    key,
                    mode=ClimateMode(
                        int(
                            self.device.get_capability_options(capability_id)[
                                "climate_on_mode"
                            ]
                        )
                    ),
                )
            else:
                client.command("climate_command", key, mode=ClimateMode.OFF)
            return
        if entity_type == "water_heater":
            client.command("water_heater_command", key, on=bool(value))
            return
        if entity_type == "siren":
            client.command("siren_command", key, state=bool(value))
            return
        if entity_type == "switch":
            write_entity_value(client, "switch", key, value)
            return

        raise ValueError(f"Unsupported entity type for onoff: {entity_type}")

    async def button(self, *, capability_id: str, **_kwargs: Any) -> None:
        self._require_client().command(
            "button_command", self._get_entity_key(capability_id)
        )

    async def number(
        self,
        value: Any,
        *,
        capability_id: str,
        **_kwargs: Any,
    ) -> None:
        write_entity_value(
            self._require_client(),
            "number",
            self._get_entity_key(capability_id),
            value,
        )

    async def select(
        self,
        value: Any,
        *,
        capability_id: str,
        **_kwargs: Any,
    ) -> None:
        write_entity_value(
            self._require_client(),
            "select",
            self._get_entity_key(capability_id),
            value,
        )
