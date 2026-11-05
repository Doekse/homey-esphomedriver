"""EspHomeClient lifecycle and command-gate tests."""

from __future__ import annotations

import asyncio
import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aioesphomeapi import (
    ZERO_NOISE_PSK,
    APIConnectionError,
    DeviceInfo,
    EntityState,
    RequiresEncryptionAPIError,
)

from homey_esphomedriver.esphome_client import (
    EspHomeClient,
    SessionState,
    provision_noise_encryption_key,
)


def _client(**kwargs: Any) -> EspHomeClient:
    return EspHomeClient("192.0.2.1", **kwargs)


def test_deep_sleep_hint_until_login_then_device_info() -> None:
    """Constructor hint holds until login; then ``DeviceInfo.has_deep_sleep`` wins."""

    async def run() -> None:
        client = _client(deep_sleep=True)
        assert client.deep_sleep is True

        client._on_state = AsyncMock()
        client._reconnect = MagicMock()
        api = MagicMock()
        api.device_info = AsyncMock(
            return_value=DeviceInfo(name="node", has_deep_sleep=False)
        )
        client._cli = api

        await client._handle_connect()

        assert client.deep_sleep is False
        assert client._reconnect.deep_sleep is False
        api.device_info_and_list_entities.assert_not_called()

    asyncio.run(run())


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
        api.device_info = AsyncMock(return_value=device_info)
        client._cli = api

        await client._handle_connect()

        assert client.state is SessionState.READY
        assert client.deep_sleep is True
        assert client._reconnect.deep_sleep is True
        api.subscribe_states.assert_called_once_with(client._dispatch_state)
        api.device_info_and_list_entities.assert_not_called()
        client.command("light_command", key=1)
        api.light_command.assert_called_once_with(key=1)

    client = _client(on_connected=on_connected)
    asyncio.run(run())


def test_stop_suppresses_disconnect_hook() -> None:
    """``stop()`` clears ``_on_state`` so teardown does not call ``on_disconnected``."""

    async def run() -> None:
        on_disconnected = AsyncMock()
        client = _client(on_disconnected=on_disconnected)
        client._on_state = AsyncMock()
        client._cli = MagicMock()
        client._cli.disconnect = AsyncMock()
        client._reconnect = MagicMock()
        client._reconnect.stop = AsyncMock()
        client._state = SessionState.READY

        await client.stop()

        assert client._on_state is None
        await client._handle_disconnect(expected_disconnect=True)
        on_disconnected.assert_not_awaited()

    asyncio.run(run())


def test_update_endpoint_adds_address_without_restart() -> None:
    """Same-port discovery appends the IP and leaves ReconnectLogic running."""

    async def run() -> None:
        client = _client()
        client._on_state = AsyncMock()
        api = MagicMock()
        api.add_addresses = MagicMock(return_value=True)
        api.disconnect = AsyncMock()
        client._cli = api
        reconnect = MagicMock()
        reconnect.stop = AsyncMock()
        client._reconnect = reconnect
        client._state = SessionState.READY

        await client.update_endpoint(host="192.0.2.2", port=6053)

        api.add_addresses.assert_called_once_with(["192.0.2.2"])
        assert client.host == "192.0.2.2"
        assert client._reconnect is reconnect
        reconnect.stop.assert_not_awaited()
        api.disconnect.assert_not_awaited()
        assert client.state is SessionState.READY

    asyncio.run(run())


def test_update_endpoint_restarts_without_reconnect() -> None:
    """A stopped reconnect (MAC mismatch) still rebuilds on a new address."""

    async def run() -> None:
        client = _client()
        client._on_state = None
        api = MagicMock()
        api.add_addresses = MagicMock()
        api.disconnect = AsyncMock()
        client._cli = api
        client._reconnect = None

        await client.update_endpoint(host="192.0.2.2", port=6053)

        api.add_addresses.assert_not_called()
        api.disconnect.assert_awaited()
        assert client.host == "192.0.2.2"
        assert client._cli is None

    asyncio.run(run())


def test_start_configures_reconnect_for_homey_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Homey discovery replaces the mDNS listener and probes live sessions."""
    kwargs: dict[str, Any] = {}
    reconnect = MagicMock()
    reconnect.start = AsyncMock()

    def factory(**passed: Any) -> MagicMock:
        kwargs.update(passed)
        return reconnect

    monkeypatch.setattr("homey_esphomedriver.esphome_client.ReconnectLogic", factory)

    async def run() -> None:
        client = _client(name="node")
        await client.start(AsyncMock())

        assert kwargs["zeroconf_wake"] is False
        assert kwargs["probe_on_announce"] is True
        assert kwargs["name"] == "node"
        reconnect.start.assert_awaited_once()

    asyncio.run(run())


def test_request_connect_notifies_device_seen() -> None:
    """A Homey sighting kicks the pending connect without restarting ReconnectLogic."""

    async def run() -> None:
        client = _client()
        reconnect = MagicMock()
        reconnect.start = AsyncMock()
        client._reconnect = reconnect

        await client.request_connect()

        reconnect.notify_device_seen.assert_called_once_with()
        reconnect.start.assert_not_awaited()

    asyncio.run(run())


def test_request_connect_without_reconnect_is_noop() -> None:
    """No running ReconnectLogic (stopped on auth or MAC mismatch) means no kick."""

    async def run() -> None:
        client = _client()
        client._reconnect = None

        await client.request_connect()

    asyncio.run(run())


def _provision_client(
    *,
    provisionable: bool = True,
    set_key: bool = True,
) -> MagicMock:
    cli = MagicMock()
    cli.connect = AsyncMock()
    cli.device_info = AsyncMock(
        return_value=DeviceInfo(api_encryption_provisionable=provisionable)
    )
    cli.noise_encryption_set_key = AsyncMock(return_value=set_key)
    cli.disconnect = AsyncMock()
    return cli


def _patch_api_client(
    monkeypatch: pytest.MonkeyPatch, cli: MagicMock
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}

    def factory(*_args: Any, **passed: Any) -> MagicMock:
        kwargs.update(passed)
        return cli

    monkeypatch.setattr("homey_esphomedriver.esphome_client.APIClient", factory)
    return kwargs


def test_provision_noise_encryption_key_sets_and_returns_psk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero-PSK session installs a generated key and never stores the zero PSK."""
    cli = _provision_client()
    kwargs = _patch_api_client(monkeypatch, cli)

    psk = asyncio.run(provision_noise_encryption_key("10.0.0.5", 6053))

    assert kwargs["noise_psk"] == ZERO_NOISE_PSK
    assert psk != ZERO_NOISE_PSK
    assert len(base64.b64decode(psk)) == 32
    cli.noise_encryption_set_key.assert_awaited_once_with(psk.encode())
    cli.disconnect.assert_awaited_once_with(force=True)


def test_provision_noise_encryption_key_requires_provisionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-provisionable devices raise and still disconnect."""
    cli = _provision_client(provisionable=False)
    _patch_api_client(monkeypatch, cli)

    with pytest.raises(RequiresEncryptionAPIError):
        asyncio.run(provision_noise_encryption_key("10.0.0.5"))

    cli.noise_encryption_set_key.assert_not_called()
    cli.disconnect.assert_awaited_once_with(force=True)


def test_provision_noise_encryption_key_rejects_failed_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected set-key still disconnects and does not return a PSK."""
    cli = _provision_client(set_key=False)
    _patch_api_client(monkeypatch, cli)

    with pytest.raises(RequiresEncryptionAPIError):
        asyncio.run(provision_noise_encryption_key("10.0.0.5"))

    cli.disconnect.assert_awaited_once_with(force=True)


def test_on_ready_runs_after_connected_returns() -> None:
    """``on_ready`` starts only once the session is READY."""
    events: list[tuple[str, SessionState]] = []

    async def on_connected(_info: DeviceInfo) -> None:
        events.append(("connected", client.state))

    async def on_ready() -> None:
        events.append(("ready", client.state))

    async def run() -> None:
        client._on_state = AsyncMock()
        client._reconnect = MagicMock()
        api = MagicMock()
        api.device_info = AsyncMock(return_value=DeviceInfo(name="node"))
        client._cli = api

        await client._handle_connect()
        await asyncio.sleep(0)

        assert events == [
            ("connected", SessionState.CONNECTED),
            ("ready", SessionState.READY),
        ]
        assert client._ready_task is not None
        assert client._ready_task.done()

    client = _client(on_connected=on_connected, on_ready=on_ready)
    asyncio.run(run())


def test_disconnect_cancels_on_ready() -> None:
    """A disconnect cancels ``on_ready`` without waiting for it inside the lock."""

    async def run() -> None:
        started = asyncio.Event()

        async def on_ready() -> None:
            started.set()
            await asyncio.Event().wait()

        client = _client(on_ready=on_ready)
        client._on_state = AsyncMock()
        client._reconnect = MagicMock()
        api = MagicMock()
        api.device_info = AsyncMock(return_value=DeviceInfo(name="node"))
        client._cli = api

        await client._handle_connect()
        await started.wait()
        task = client._ready_task
        assert task is not None

        await client._handle_disconnect(expected_disconnect=True)

        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()

    asyncio.run(run())


def test_stop_cancels_on_ready() -> None:
    """Stopping the session cancels an in-flight ``on_ready`` task."""

    async def run() -> None:
        started = asyncio.Event()

        async def on_ready() -> None:
            started.set()
            await asyncio.Event().wait()

        client = _client(on_ready=on_ready)
        client._on_state = AsyncMock()
        client._reconnect = MagicMock()
        client._reconnect.stop = AsyncMock()
        api = MagicMock()
        api.device_info = AsyncMock(return_value=DeviceInfo(name="node"))
        api.disconnect = AsyncMock()
        client._cli = api

        await client._handle_connect()
        await started.wait()
        task = client._ready_task
        assert task is not None

        await client.stop()

        assert task.cancelled()

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
