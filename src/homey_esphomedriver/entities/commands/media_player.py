"""Homey speaker / volume capabilities → ESPHome media player / siren."""

from __future__ import annotations

from typing import Any

from aioesphomeapi import MediaPlayerCommand

from homey_esphomedriver.entities.commands.base import AbstractEntityCommandHandler


class MediaPlayerEntityCommandHandler(AbstractEntityCommandHandler):
    CAPABILITIES = (
        "speaker_playing",
        "speaker_stop",
        "volume_set",
        "volume_mute",
        "volume_up",
        "volume_down",
    )
    ENTITY_TYPE = "media_player"

    async def speaker_playing(
        self,
        value: Any,
        capability_id: str = "speaker_playing",
        **_kwargs: Any,
    ) -> None:
        key = self._get_entity_key(capability_id)
        client = self._require_client()
        if value:
            client.command("media_player_command", key, command=MediaPlayerCommand.PLAY)
            return
        if self.device.get_capability_options(capability_id)["supports_pause"]:
            client.command(
                "media_player_command", key, command=MediaPlayerCommand.PAUSE
            )
            return
        client.command("media_player_command", key, command=MediaPlayerCommand.STOP)

    async def speaker_stop(
        self,
        _value: Any = True,
        capability_id: str = "speaker_stop",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "media_player_command",
            self._get_entity_key(capability_id),
            command=MediaPlayerCommand.STOP,
        )

    async def volume_set(
        self,
        value: Any,
        capability_id: str = "volume_set",
        **_kwargs: Any,
    ) -> None:
        key = self._get_entity_key(capability_id)
        volume = float(value)
        client = self._require_client()
        if self._get_entity_type(capability_id) == "siren":
            client.command("siren_command", key, volume=volume)
            return
        client.command("media_player_command", key, volume=volume)

    async def volume_mute(
        self,
        value: Any,
        capability_id: str = "volume_mute",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "media_player_command",
            self._get_entity_key(capability_id),
            command=(MediaPlayerCommand.MUTE if value else MediaPlayerCommand.UNMUTE),
        )

    async def volume_up(
        self,
        _value: Any = True,
        capability_id: str = "volume_up",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "media_player_command",
            self._get_entity_key(capability_id),
            command=MediaPlayerCommand.VOLUME_UP,
        )

    async def volume_down(
        self,
        _value: Any = True,
        capability_id: str = "volume_down",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "media_player_command",
            self._get_entity_key(capability_id),
            command=MediaPlayerCommand.VOLUME_DOWN,
        )
