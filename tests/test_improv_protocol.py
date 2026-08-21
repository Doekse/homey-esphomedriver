"""Improv BLE frame-codec tests.

Pins checksum, RPC 0x01 construction, BLE write chunking, characteristic
parsing, and advertisement service-data extraction. No BLE stack is required.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from homey_esphomedriver.pairing.ble_protocol import (
    ERROR_NONE,
    ERROR_UNABLE_TO_CONNECT,
    ERROR_UNKNOWN,
    SERVICE_DATA_UUID,
    STATE_AUTHORIZED,
    WRITE_CHUNK_SIZE,
    ImprovError,
    advertisement_state,
    build_wifi_settings,
    checksum,
    error_key,
    iter_write_chunks,
    parse_error,
    parse_state,
)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"", 0),
        (bytes((0x01, 0xFF)), 0x00),
        (b"\x10\x20", 0x30),
    ],
)
def test_checksum_is_lsb_of_sum(data: bytes, expected: int) -> None:
    assert checksum(data) == expected


def test_build_wifi_settings_frame_round_trips_lengths() -> None:
    frame = build_wifi_settings("net", "secret")
    assert frame[0] == 0x01
    data_len = frame[1]
    data = frame[2 : 2 + data_len]
    assert data[0] == 3
    assert data[1:4] == b"net"
    assert data[4] == 6
    assert data[5:11] == b"secret"
    assert frame[-1] == checksum(frame[:-1])


def test_build_wifi_settings_rejects_overlong_ssid() -> None:
    with pytest.raises(ImprovError) as caught:
        build_wifi_settings("x" * 256, "pw")
    assert caught.value.key == "errors.improv.ssid_too_long"


def test_iter_write_chunks_splits_on_ble_mtu() -> None:
    frame = bytes(range(45))
    chunks = iter_write_chunks(frame)
    assert all(len(chunk) <= WRITE_CHUNK_SIZE for chunk in chunks)
    assert b"".join(chunks) == frame
    assert len(chunks) == 3


def test_parse_state_reads_first_byte() -> None:
    assert parse_state(bytes((STATE_AUTHORIZED, 0x99))) == STATE_AUTHORIZED


def test_parse_state_rejects_empty() -> None:
    with pytest.raises(ImprovError) as caught:
        parse_state(b"")
    assert caught.value.key == "errors.improv.invalid_value"


def test_parse_error_defaults_to_none() -> None:
    assert parse_error(b"") == ERROR_NONE
    assert parse_error(bytes((ERROR_UNABLE_TO_CONNECT,))) == ERROR_UNABLE_TO_CONNECT


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (ERROR_UNABLE_TO_CONNECT, "errors.improv.unable_to_connect"),
        (ERROR_UNKNOWN, "errors.improv.unknown"),
        (0x42, "errors.improv.unknown"),
    ],
)
def test_error_key(code: int, expected: str) -> None:
    assert error_key(code) == expected


def test_advertisement_state_from_dict_entry() -> None:
    data = [{"uuid": SERVICE_DATA_UUID, "data": bytes((STATE_AUTHORIZED,))}]
    assert advertisement_state(data) == STATE_AUTHORIZED


def test_advertisement_state_accepts_short_uuid_and_dashed() -> None:
    dashed = "00004677-0000-1000-8000-00805f9b34fb"
    assert advertisement_state([{"uuid": dashed, "data": b"\x02"}]) == 0x02
    assert advertisement_state([{"uuid": "4677", "data": [0x03]}]) == 0x03


def test_advertisement_state_from_object_entry() -> None:
    entry = SimpleNamespace(uuid=SERVICE_DATA_UUID, data=bytearray((STATE_AUTHORIZED,)))
    assert advertisement_state([entry]) == STATE_AUTHORIZED


@pytest.mark.parametrize(
    "payload",
    [None, [], [{"uuid": "not-improv", "data": b"\x01"}]],
)
def test_advertisement_state_returns_none_when_missing(payload: object) -> None:
    assert advertisement_state(payload) is None
