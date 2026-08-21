"""Improv Wi-Fi BLE frame codec (https://www.improv-wifi.com/ble/)."""

from __future__ import annotations

# Homey BLE APIs use 128-bit lowercase UUIDs with no dashes.
SERVICE_UUID = "00467768622822724663277478268000"
CHAR_STATE = "00467768622822724663277478268001"
CHAR_ERROR = "00467768622822724663277478268002"
CHAR_RPC_COMMAND = "00467768622822724663277478268003"

# Advertised as 16-bit 0x4677 on the standard BLE base UUID.
SERVICE_DATA_UUID = "0000467700001000800000805f9b34fb"

STATE_AUTHORIZATION_REQUIRED = 0x01
STATE_AUTHORIZED = 0x02
STATE_PROVISIONING = 0x03
STATE_PROVISIONED = 0x04

ERROR_NONE = 0x00
ERROR_INVALID_RPC = 0x01
ERROR_UNKNOWN_RPC = 0x02
ERROR_UNABLE_TO_CONNECT = 0x03
ERROR_NOT_AUTHORIZED = 0x04
ERROR_UNKNOWN = 0xFF

RPC_WIFI_SETTINGS = 0x01

WRITE_CHUNK_SIZE = 20
"""Improv spec: payloads over 20 bytes need multiple BLE packets."""

_ERROR_KEYS = {
    ERROR_INVALID_RPC: "errors.improv.invalid_rpc",
    ERROR_UNKNOWN_RPC: "errors.improv.unknown_rpc",
    ERROR_UNABLE_TO_CONNECT: "errors.improv.unable_to_connect",
    ERROR_NOT_AUTHORIZED: "errors.improv.not_authorized",
    ERROR_UNKNOWN: "errors.improv.unknown",
}


class ImprovError(Exception):
    """Improv failure identified by a locales key."""

    def __init__(self, key: str) -> None:
        """
        Args:
            key: Locales key under ``errors.improv.*``.
        """
        self.key = key
        super().__init__(key)


def checksum(data: bytes) -> int:
    """LSB of the sum of ``data``."""
    return sum(data) & 0xFF


def build_wifi_settings(ssid: str, password: str) -> bytes:
    """Build RPC 0x01 with UTF-8 SSID and password."""
    ssid_bytes = ssid.encode("utf-8")
    password_bytes = password.encode("utf-8")
    if len(ssid_bytes) > 255 or len(password_bytes) > 255:
        raise ImprovError("errors.improv.ssid_too_long")
    data = (
        bytes((len(ssid_bytes),))
        + ssid_bytes
        + bytes((len(password_bytes),))
        + password_bytes
    )
    payload = bytes((RPC_WIFI_SETTINGS, len(data))) + data
    return payload + bytes((checksum(payload),))


def iter_write_chunks(frame: bytes, size: int = WRITE_CHUNK_SIZE) -> tuple[bytes, ...]:
    """Split an RPC frame into BLE-sized writes."""
    return tuple(frame[index : index + size] for index in range(0, len(frame), size))


def parse_state(data: bytes) -> int:
    """Read the current-state characteristic (one byte)."""
    if not data:
        raise ImprovError("errors.improv.invalid_value")
    return data[0]


def parse_error(data: bytes) -> int:
    """Read the error-state characteristic (one byte)."""
    return data[0] if data else ERROR_NONE


def error_key(code: int) -> str:
    """Map an Improv error byte to a locales key."""
    return _ERROR_KEYS.get(code, _ERROR_KEYS[ERROR_UNKNOWN])


def advertisement_state(service_data: object) -> int | None:
    """Return Improv current state from advertisement service data, if present."""
    if not service_data:
        return None
    for entry in service_data:
        if isinstance(entry, dict):
            uuid, raw = entry.get("uuid"), entry.get("data") or b""
        else:
            uuid = getattr(entry, "uuid", None)
            raw = getattr(entry, "data", b"") or b""
        if uuid is None:
            continue
        cleaned = str(uuid).replace("-", "").lower()
        if cleaned not in {SERVICE_DATA_UUID, "4677"}:
            continue
        payload = _as_bytes(raw)
        if payload:
            return payload[0]
    return None


def _as_bytes(data: object) -> bytes:
    if isinstance(data, bytes):
        return data
    if isinstance(data, (bytearray, memoryview, list, tuple)):
        return bytes(data)
    return b""
