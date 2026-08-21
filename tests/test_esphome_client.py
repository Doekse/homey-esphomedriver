"""EspHomeClient lifecycle and command-gate tests."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aioesphomeapi import APIConnectionError, DeviceInfo, EntityState

from homey_esphomedriver.esphome_client import EspHomeClient, SessionState


def _client(**kwargs: Any) -> EspHomeClient:
    return EspHomeClient("192.0.2.1", **kwargs)


def test_on_connected_awaited_before_ready() -> None:
    """Commands stay blocked until ``on_connected`` returns."""

    async def on_connected(_info: DeviceInfo) -> None:
        assert client.state is SessionState.CONNECTED
        with pytest.raises(APIConnectionError, match="not ready"):
            client.command("light_command", key=1)

    async def run() -> None:
        client._on_state = AsyncMock()
        client._reconnect = MagicMock()
        device_info = DeviceInfo(name="node", has_deep_sleep=True)

        api = MagicMock()
        api.device_info_and_list_entities = AsyncMock(
            return_value=(device_info, [], [])
        )
        client._cli = api

        await client._handle_connect()

        assert client.state is SessionState.READY
        assert client.deep_sleep is True
        assert client._reconnect.deep_sleep is True
        api.subscribe_states.assert_called_once_with(client._dispatch_state)
        client.command("light_command", key=1)
        api.light_command.assert_called_once_with(key=1)

    client = _client(on_connected=on_connected)
    asyncio.run(run())


def test_async_on_state_is_invoked() -> None:
    """The sync ``subscribe_states`` hop invokes the async ``on_state`` callback."""
    received: list[EntityState] = []

    async def on_state(state: EntityState) -> None:
        received.append(state)

    async def run() -> None:
        client = _client()
        client._on_state = on_state
        client._dispatch_state(EntityState(key=7))
        await asyncio.sleep(0)
        assert len(received) == 1
        assert received[0].key == 7

    asyncio.run(run())
