"""Homey-radio Improv client: scan, provision Wi-Fi, disconnect."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from homey_esphomedriver.pairing.ble_protocol import (
    CHAR_ERROR,
    CHAR_RPC_COMMAND,
    CHAR_STATE,
    ERROR_NONE,
    ERROR_NOT_AUTHORIZED,
    ERROR_UNABLE_TO_CONNECT,
    SERVICE_UUID,
    STATE_AUTHORIZATION_REQUIRED,
    STATE_AUTHORIZED,
    STATE_PROVISIONED,
    STATE_PROVISIONING,
    ImprovError,
    advertisement_state,
    build_wifi_settings,
    error_key,
    iter_write_chunks,
    parse_error,
    parse_state,
)

_AUTHORIZE_TIMEOUT_S = 60.0
_PROVISION_TIMEOUT_S = 30.0
_CONNECT_ATTEMPTS = 3
_CONNECT_RETRY_S = 1.0


class ImprovBleClient:
    """Talk Improv GATT on Homey's BLE radio."""

    def __init__(
        self,
        homey: Any,
        *,
        debug: Callable[..., None] | None = None,
    ) -> None:
        """Create a client that uses Homey's BLE radio.

        Args:
            homey: Homey instance whose BLE manager is used for scan and GATT.
            debug: Optional debug logger.
        """
        self._homey = homey
        self._debug = debug or (lambda *_args: None)
        self._peripheral: Any | None = None
        self._state_char: Any | None = None
        self._error_char: Any | None = None
        self._state = 0
        self._error = ERROR_NONE
        self._changed = asyncio.Event()
        self._connect_lock = asyncio.Lock()

    async def discover(self) -> list[dict[str, str]]:
        """Return connectable Improv peripherals Homey can currently see."""
        advertisements = await self._homey.ble.discover([SERVICE_UUID])
        devices: list[dict[str, str]] = []
        seen: set[str] = set()
        for advertisement in advertisements:
            uuid = advertisement.uuid
            if not uuid or uuid in seen or not advertisement.connectable:
                continue
            if advertisement_state(advertisement.service_data) == STATE_PROVISIONED:
                continue
            seen.add(uuid)
            name = advertisement.local_name or advertisement.address or "ESPHome device"
            devices.append({"uuid": uuid, "name": str(name)})
        return devices

    async def connect(self, peripheral_uuid: str) -> None:
        """Open GATT and wait until the device will accept credentials."""
        async with self._connect_lock:
            if self._peripheral is not None:
                return
            self._debug("Connecting over Bluetooth…")
            peripheral = await self._open_gatt(peripheral_uuid)
            try:
                await self._subscribe(peripheral)
                await self._ensure_authorized()
            except Exception:
                await self._disconnect(peripheral)
                raise
            self._peripheral = peripheral

    async def send_wifi(self, ssid: str, password: str) -> None:
        """Write Wi-Fi credentials on an already-open GATT session."""
        peripheral = self._peripheral
        if peripheral is None:
            raise ImprovError("errors.improv.not_connected")

        await self._ensure_authorized()

        self._error = ERROR_NONE
        self._debug("Sending Wi-Fi credentials…")
        for chunk in iter_write_chunks(build_wifi_settings(ssid, password)):
            await peripheral.write(SERVICE_UUID, CHAR_RPC_COMMAND, chunk)

        await self._wait_until(
            lambda: (
                self._state == STATE_PROVISIONED
                or self._error in {ERROR_UNABLE_TO_CONNECT, ERROR_NOT_AUTHORIZED}
                or (self._error != ERROR_NONE and self._state != STATE_PROVISIONING)
            ),
            _PROVISION_TIMEOUT_S,
            "errors.improv.setup_timeout",
        )
        if self._error != ERROR_NONE:
            raise ImprovError(error_key(self._error))
        if self._state != STATE_PROVISIONED:
            raise ImprovError("errors.improv.setup_incomplete")
        self._debug("Device joined Wi-Fi")

    async def close(self) -> None:
        """Drop the GATT connection if one is open."""
        peripheral = self._peripheral
        self._peripheral = None
        if peripheral is not None:
            await self._disconnect(peripheral)

    async def _open_gatt(self, peripheral_uuid: str) -> Any:
        """Find the peripheral, then connect with retries."""
        try:
            advertisement = await self._homey.ble.find(peripheral_uuid)
        except Exception as err:
            raise ImprovError("errors.improv.bluetooth_connect") from err

        last_error: BaseException | None = None
        for attempt in range(_CONNECT_ATTEMPTS):
            try:
                return await advertisement.connect()
            except Exception as err:
                last_error = err
                self._debug("Improv GATT connect failed", attempt + 1, err)
                if attempt + 1 == _CONNECT_ATTEMPTS:
                    break
                await asyncio.sleep(_CONNECT_RETRY_S)
                try:
                    advertisement = await self._homey.ble.find(peripheral_uuid)
                except Exception as find_err:
                    self._debug("Improv find after connect failure", find_err)
        raise ImprovError("errors.improv.bluetooth_connect") from last_error

    async def _subscribe(self, peripheral: Any) -> None:
        service = await peripheral.get_service(SERVICE_UUID)
        self._state_char = await service.get_characteristic(CHAR_STATE)
        self._error_char = await service.get_characteristic(CHAR_ERROR)
        await self._state_char.subscribe_to_notifications(self._on_state)
        await self._error_char.subscribe_to_notifications(self._on_error)

    def _on_state(self, data: object) -> None:
        self._state = parse_state(_coerce_bytes(data))
        self._changed.set()

    def _on_error(self, data: object) -> None:
        self._error = parse_error(_coerce_bytes(data))
        self._changed.set()

    async def _ensure_authorized(self) -> None:
        await self._refresh()
        if self._state == STATE_PROVISIONED:
            raise ImprovError("errors.improv.already_provisioned")
        if self._state == STATE_AUTHORIZATION_REQUIRED:
            self._debug("Press the button on the device")
            await self._wait_until(
                lambda: self._state == STATE_AUTHORIZED or self._error != ERROR_NONE,
                _AUTHORIZE_TIMEOUT_S,
                "errors.improv.not_authorized",
            )
        if self._error != ERROR_NONE and self._error != ERROR_UNABLE_TO_CONNECT:
            raise ImprovError(error_key(self._error))
        if self._state != STATE_AUTHORIZED:
            raise ImprovError("errors.improv.not_ready")

    async def _refresh(self) -> None:
        self._state = parse_state(_coerce_bytes(await self._state_char.read()))
        self._error = parse_error(_coerce_bytes(await self._error_char.read()))

    async def _wait_until(
        self,
        predicate: Callable[[], bool],
        timeout: float,
        timeout_message: str,
    ) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            if predicate():
                return
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise ImprovError(timeout_message)
            self._changed.clear()
            if predicate():
                return
            try:
                await asyncio.wait_for(self._changed.wait(), remaining)
            except TimeoutError:
                raise ImprovError(timeout_message) from None

    async def _disconnect(self, peripheral: Any) -> None:
        # After STATE_PROVISIONED the peripheral often drops BLE, and
        # unsubscribeToNotifications can hang until Homey's emit timeout.
        self._state_char = None
        self._error_char = None
        try:
            await peripheral.disconnect()
        except Exception as err:
            self._debug("Improv BLE disconnect failed", err)


def _coerce_bytes(data: object) -> bytes:
    """Normalize Homey GATT values.

    Homey usually returns ``bytes``. JS Buffers may arrive as a list of ints.
    """
    if isinstance(data, bytes):
        return data
    if isinstance(data, (bytearray, memoryview, list, tuple)):
        return bytes(data)
    raise ImprovError("errors.improv.invalid_value")
