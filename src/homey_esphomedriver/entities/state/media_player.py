"""Push ESPHome MediaPlayerEntityState into Homey speaker and volume capabilities."""

from __future__ import annotations

from typing import cast

from aioesphomeapi import EntityState, MediaPlayerEntityState, MediaPlayerState

from homey_esphomedriver.entities.state.base import (
    AbstractEntityStateUpdateHandler,
)

_PLAYING_STATES = frozenset(
    {
        MediaPlayerState.PLAYING,
        MediaPlayerState.ANNOUNCING,
    }
)


class MediaPlayerEntityStateUpdateHandler(AbstractEntityStateUpdateHandler):
    async def handle(self, state: EntityState, capabilities: list[str]) -> None:
        media = cast(MediaPlayerEntityState, state)

        playing_id = self.find_capability(capabilities, "speaker_playing")
        if playing_id is not None:
            self.set_capability_value(
                playing_id,
                media.state in _PLAYING_STATES,
            )

        volume_id = self.find_capability(capabilities, "volume_set")
        if volume_id is not None:
            self.set_capability_value(volume_id, float(media.volume))

        mute_id = self.find_capability(capabilities, "volume_mute")
        if mute_id is not None:
            self.set_capability_value(mute_id, bool(media.muted))
