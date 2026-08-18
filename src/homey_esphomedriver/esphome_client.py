"""Per-device Native API session used by pairing and runtime.

Homey keeps one ESPHome node per device. Pairing uses a one-shot probe;
runtime devices keep :class:`~aioesphomeapi.ReconnectLogic` so drops recover
and state subscriptions re-arm on each connect.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aioesphomeapi import (
    APIClient,
    APIConnectionError,
    DeviceInfo,
    EntityInfo,
    EntityState,
    ReconnectLogic,
    UserService,
)
from aioesphomeapi.api_pb2 import SubscribeStatesRequest

from homey_esphomedriver.esphome_util import (
    is_device_mismatch,
    normalize_mac,
    should_stop_reconnect,
)
from homey_esphomedriver.profile import DEFAULT_CLIENT_INFO

DEFAULT_API_PORT = 6053
"""ESPHome native API port used when discovery omits it."""

StateCallback = Callable[[EntityState], None]
ConnectedCallback = Callable[[DeviceInfo], Awaitable[None]]
DisconnectedCallback = Callable[[bool], Awaitable[None]]
ConnectErrorCallback = Callable[[Exception], Awaitable[None]]
DebugCallback = Callable[..., None]


class EspHomeClient:
    """
    Native API session for one ESPHome node.

    Pairing uses :meth:`probe` without reconnect. Runtime devices call
    :meth:`start` so drops recover via ReconnectLogic and state subscriptions
    re-arm on each connect.
    """

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_API_PORT,
        *,
        name: str | None = None,
        noise_psk: str | None = None,
        expected_mac: str | None = None,
        on_state: StateCallback | None = None,
        on_connected: ConnectedCallback | None = None,
        on_disconnected: DisconnectedCallback | None = None,
        on_connect_error: ConnectErrorCallback | None = None,
        debug: DebugCallback | None = None,
        error: DebugCallback | None = None,
        client_info: str = DEFAULT_CLIENT_INFO,
        deep_sleep: bool = False,
    ) -> None:
        """Create a session for one ESPHome node.

        Args:
            host: Node address from discovery or settings.
            port: Native API port.
            name: Hostname used by ReconnectLogic logs and zeroconf.
            noise_psk: Noise encryption key, or ``None`` for plaintext.
            expected_mac: Paired MAC; a mismatch stops reconnect at that address.
            on_state: Sync callback for subscribed entity states.
            on_connected: Called after login and state subscription.
            on_disconnected: Called with whether the drop was expected.
            on_connect_error: Called when a connect attempt fails.
            debug: Optional debug logger.
            error: Optional error logger for callback failures.
            client_info: Name shown on the node for this Homey client.
            deep_sleep: Treat disconnects as expected while the node is sleeping.
        """
        if not host:
            raise ValueError("ESPHome host is required")

        self._host = host
        self._port = int(port) if port else DEFAULT_API_PORT
        self._name = name or None
        self._noise_psk = noise_psk or None
        self._expected_mac = normalize_mac(expected_mac) if expected_mac else None
        self._client_info = client_info
        self._deep_sleep = deep_sleep

        self._on_state = on_state
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._on_connect_error = on_connect_error
        self._debug_log = debug
        self._error_log = error

        self._cli: APIClient | None = None
        self._reconnect: ReconnectLogic | None = None
        self._device_info: DeviceInfo | None = None
        self._started = False
        self._available = False

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def available(self) -> bool:
        """Whether the session is currently ready for commands."""
        return self._available

    @property
    def device_info(self) -> DeviceInfo | None:
        return self._device_info

    @property
    def api(self) -> APIClient:
        """Underlying aioesphomeapi client.

        Raises:
            APIConnectionError: If the client has not been constructed yet.
        """
        if self._cli is None:
            raise APIConnectionError("ESPHome client has not been created yet")
        return self._cli

    async def probe(
        self,
    ) -> tuple[DeviceInfo, list[EntityInfo], list[UserService]]:
        """Connect once, list entities, then disconnect.

        Used by the pair loading view. Leaves the client disconnected so the
        runtime path can :meth:`start` with ReconnectLogic afterward.
        """
        await self._ensure_stopped()
        self._debug(
            f"Connecting once to {self._host}:{self._port} "
            f"encrypted={self._noise_psk is not None}"
        )
        cli = self._create_client()
        self._cli = cli
        try:
            await cli.connect(login=True)
            device_info, entities, services = await cli.device_info_and_list_entities()
            self._device_info = device_info
            self._debug(
                f"Listed {len(entities)} entities / {len(services)} services "
                f"from {device_info.name}"
            )
            return device_info, entities, services
        finally:
            await self.disconnect()

    async def start(self) -> None:
        """Start ReconnectLogic and keep the node connected at runtime."""
        if self._started:
            return

        await self._ensure_stopped()
        self._debug(
            f"Starting reconnect session {self._host}:{self._port} "
            f"encrypted={self._noise_psk is not None}"
        )
        self._cli = self._create_client()
        self._reconnect = ReconnectLogic(
            client=self._cli,
            on_connect=self._handle_connect,
            on_disconnect=self._handle_disconnect,
            name=self._name,
            on_connect_error=self._handle_connect_error,
        )
        self._reconnect.deep_sleep = self._deep_sleep
        self._started = True
        await self._reconnect.start()

    async def stop(self) -> None:
        """Stop reconnect attempts and close the API session."""
        self._debug(f"Stopping session {self._host}:{self._port}")
        await self._ensure_stopped()
        self._available = False
        self._device_info = None

    async def disconnect(self) -> None:
        """Close a one-shot session without touching ReconnectLogic state."""
        self._available = False
        if self._cli is not None:
            await self._cli.disconnect(force=True)
        self._cli = None

    async def update_endpoint(self, *, host: str, port: int) -> None:
        """Apply a discovery address change and restart ReconnectLogic if running."""
        was_started = self._started
        self._host = host
        self._port = port
        self._debug(
            f"Updating endpoint {self._host}:{self._port} "
            f"encrypted={self._noise_psk is not None} restart={was_started}"
        )
        await self._ensure_stopped()
        if was_started:
            await self.start()

    async def request_connect(self) -> None:
        """Retry now if ReconnectLogic is waiting (Homey saw the node on mDNS)."""
        if self._reconnect is None:
            return
        await self._reconnect.start()

    def command(self, name: str, *args: Any, **kwargs: Any) -> None:
        """Forward a native API command.

        Args:
            name: ``APIClient`` method such as ``light_command``.
        """
        self._debug(name, args, kwargs)
        getattr(self.api, name)(*args, **kwargs)

    def request_states(self) -> None:
        """Re-request a state dump without registering another listener.

        Used after diagnostic/config capabilities are added at runtime so they
        receive current values without stacking subscribe callbacks.
        """
        self.api._get_connection().send_message(SubscribeStatesRequest())

    async def list_entities_services(
        self,
    ) -> tuple[list[EntityInfo], list[UserService]]:
        """List entities on the current connection."""
        return await self.api.list_entities_services()

    def _create_client(self) -> APIClient:
        """Build a fresh APIClient from the current endpoint settings."""
        return APIClient(
            self._host,
            self._port,
            client_info=self._client_info,
            noise_psk=self._noise_psk,
            expected_mac=self._expected_mac,
        )

    async def _ensure_stopped(self) -> None:
        """Tear down ReconnectLogic and any open socket."""
        reconnect = self._reconnect
        self._reconnect = None
        self._started = False
        self._available = False

        if reconnect is not None:
            await reconnect.stop()

        if self._cli is not None:
            await self._cli.disconnect(force=True)
            self._cli = None

    async def _handle_connect(self) -> None:
        """Re-subscribe and refresh device info whenever ReconnectLogic logs in."""
        cli = self.api
        try:
            device_info, _, _ = await cli.device_info_and_list_entities()
            self._device_info = device_info
            self._name = device_info.name
            self._deep_sleep = device_info.has_deep_sleep
            if self._reconnect is not None:
                self._reconnect.name = device_info.name
            if self._on_state is None:
                raise ValueError("State callback is required to subscribe")
            cli.subscribe_states(self._on_state)
            self._available = True
            self._debug(f"Connected to {device_info.name} ({self._host}:{self._port})")
        except APIConnectionError as err:
            self._available = False
            self._debug(f"ESPHome setup failed for {self._host}:{self._port}: {err}")
            # ReconnectLogic only schedules another attempt after on_stop.
            await cli.disconnect()
            return

        if self._on_connected is not None:
            self._schedule(self._on_connected(device_info))

    async def _handle_disconnect(self, expected_disconnect: bool) -> None:
        self._available = False
        self._debug(
            f"Disconnected from {self._host}:{self._port} "
            f"expected={expected_disconnect}"
        )
        if self._on_disconnected is not None:
            self._schedule(self._on_disconnected(expected_disconnect))

    async def _handle_connect_error(self, error: Exception) -> None:
        self._available = False
        self._debug(f"Connect error for {self._host}:{self._port}: {error}")
        if self._on_connect_error is not None:
            self._schedule(self._on_connect_error(error))
        if self._reconnect is None:
            return
        if should_stop_reconnect(error):
            await self._reconnect.stop()
            self._reconnect = None
            self._started = False
        elif is_device_mismatch(error):
            # Keep _started so a later discovery address change can restart.
            await self._reconnect.stop()
            self._reconnect = None

    def _schedule(self, coro: Awaitable[None]) -> None:
        task = asyncio.ensure_future(coro)
        task.add_done_callback(self._on_callback_done)

    def _on_callback_done(self, task: asyncio.Future[Any]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None and self._error_log is not None:
            self._error_log(error)

    def _debug(self, *args: object) -> None:
        if self._debug_log is not None:
            self._debug_log(*args)


async def probe_esphome_device(
    host: str,
    port: int = DEFAULT_API_PORT,
    *,
    noise_psk: str | None = None,
    client_info: str = DEFAULT_CLIENT_INFO,
    debug: DebugCallback | None = None,
) -> tuple[DeviceInfo, list[EntityInfo], list[UserService]]:
    """One-shot probe for the pairing loading view."""
    client = EspHomeClient(
        host,
        port,
        noise_psk=noise_psk,
        client_info=client_info,
        debug=debug,
    )
    return await client.probe()
