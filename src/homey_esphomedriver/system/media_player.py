"""Media player: on/off, play/pause, stop and volume."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from aioesphomeapi import (
    MediaPlayerCommand,
    MediaPlayerEntityFeature,
    MediaPlayerInfo,
    MediaPlayerState,
)

from homey_esphomedriver.system import BoundEntity, SystemCapability

_PLAYING = frozenset({MediaPlayerState.PLAYING, MediaPlayerState.ANNOUNCING})


def supports_pause(info: MediaPlayerInfo) -> bool:
    """Whether stopping playback can pause instead of stop."""
    if info.feature_flags:
        return bool(info.feature_flags & MediaPlayerEntityFeature.PAUSE)
    return bool(info.supports_pause)


def _command(command: MediaPlayerCommand) -> SystemCapability:
    def set_command(
        value: Any, opts: Mapping[str, Any], entity: BoundEntity
    ) -> dict[str, Any]:
        del value, opts, entity
        return {"command": command}

    return SystemCapability(set_parser=set_command)


def _report_onoff(state: Any, entity: BoundEntity) -> bool | None:
    del entity
    if state.state is None or state.state == MediaPlayerState.NONE:
        return None
    return state.state != MediaPlayerState.OFF


def _set_onoff(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts
    feature = (
        MediaPlayerEntityFeature.TURN_ON if value else MediaPlayerEntityFeature.TURN_OFF
    )
    flags = cast(MediaPlayerInfo, entity.info).feature_flags
    if flags and not flags & feature:
        raise ValueError(f"Media player cannot turn {'on' if value else 'off'}")
    return {
        "command": MediaPlayerCommand.TURN_ON if value else MediaPlayerCommand.TURN_OFF
    }


def _report_playing(state: Any, entity: BoundEntity) -> bool:
    del entity
    return state.state in _PLAYING


def _set_playing(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts
    if value:
        return {"command": MediaPlayerCommand.PLAY}
    if supports_pause(cast(MediaPlayerInfo, entity.info)):
        return {"command": MediaPlayerCommand.PAUSE}
    return {"command": MediaPlayerCommand.STOP}


def _report_volume(state: Any, entity: BoundEntity) -> float:
    del entity
    return float(state.volume)


def _set_volume(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts, entity
    return {"volume": float(value)}


def _report_mute(state: Any, entity: BoundEntity) -> bool:
    del entity
    return bool(state.muted)


def _set_mute(
    value: Any, opts: Mapping[str, Any], entity: BoundEntity
) -> dict[str, Any]:
    del opts, entity
    return {"command": MediaPlayerCommand.MUTE if value else MediaPlayerCommand.UNMUTE}


CAPABILITIES: dict[str, SystemCapability] = {
    "onoff": SystemCapability(report_parser=_report_onoff, set_parser=_set_onoff),
    "speaker_playing": SystemCapability(
        report_parser=_report_playing, set_parser=_set_playing
    ),
    "speaker_stop": _command(MediaPlayerCommand.STOP),
    "volume_set": SystemCapability(
        report_parser=_report_volume, set_parser=_set_volume
    ),
    "volume_mute": SystemCapability(report_parser=_report_mute, set_parser=_set_mute),
    "volume_up": _command(MediaPlayerCommand.VOLUME_UP),
    "volume_down": _command(MediaPlayerCommand.VOLUME_DOWN),
}
