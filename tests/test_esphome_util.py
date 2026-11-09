"""Shared helper tests.

Covers the pure formatting helpers and the native-API error classification that
drives pairing prompts, reconnect back-off and the locales keys shown to users.
``is_debug_enabled`` / ``debug_log`` / ``attach_library_logs`` need a stubbed
``Homey.env``; ``homey-stubs`` ships annotations only.
"""

from __future__ import annotations

import logging
import sys
import types
from collections.abc import Iterator
from typing import Any

import pytest
from aioesphomeapi import (
    BadMACAddressAPIError,
    BadNameAPIError,
    DeviceInfo,
    EncryptionHelloAPIError,
    EncryptionPlaintextAPIError,
    HandshakeAPIError,
    InvalidAuthAPIError,
    InvalidEncryptionKeyAPIError,
    RequiresEncryptionAPIError,
    ResolveAPIError,
)
from aioesphomeapi.core import APIConnectionError, TimeoutAPIError

import homey_esphomedriver.esphome_util as esphome_util
from homey_esphomedriver.esphome_util import (
    attach_library_logs,
    changed_values,
    debug_log,
    device_info_settings,
    error_key,
    format_project,
    format_webserver,
    invalid_encryption_key,
    is_debug_enabled,
    is_device_mismatch,
    needs_encryption_key,
    normalize_mac,
    requires_encryption,
    should_stop_reconnect,
)


@pytest.fixture
def homey_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, object]]:
    """Install a stub ``homey.homey.Homey`` with a mutable ``env`` mapping."""
    env: dict[str, object] = {}
    package = types.ModuleType("homey")
    module = types.ModuleType("homey.homey")

    class Homey:
        pass

    Homey.env = env
    module.Homey = Homey
    monkeypatch.setitem(sys.modules, "homey", package)
    monkeypatch.setitem(sys.modules, "homey.homey", module)
    is_debug_enabled.cache_clear()
    yield env
    is_debug_enabled.cache_clear()


@pytest.fixture
def reset_library_logs() -> Iterator[None]:
    """Reset the idempotent library-log attach flag and any added handlers."""
    logger = logging.getLogger("aioesphomeapi")
    before = list(logger.handlers)
    esphome_util._library_logs_attached = False
    yield
    esphome_util._library_logs_attached = False
    for handler in list(logger.handlers):
        if handler not in before:
            logger.removeHandler(handler)


@pytest.mark.parametrize(
    "raw",
    ["AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff", "AABBCCDDEEFF", "aabbccddeeff"],
)
def test_normalize_mac_is_separator_and_case_insensitive(raw: str) -> None:
    assert normalize_mac(raw) == "aabbccddeeff"


@pytest.mark.parametrize(
    ("name", "version", "expected"),
    [
        ("Brand.AQ-1", "1.0.0", "Brand.AQ-1 1.0.0"),
        ("Brand.AQ-1", "", "Brand.AQ-1"),
        ("", "1.0.0", "1.0.0"),
        ("", "", ""),
    ],
)
def test_format_project(name: str, version: str, expected: str) -> None:
    assert format_project(name, version) == expected


@pytest.mark.parametrize(
    ("host", "port", "expected"),
    [
        ("192.168.1.10", 80, "http://192.168.1.10:80"),
        ("192.168.1.10", 0, ""),
        ("192.168.1.10", -1, ""),
        ("", 80, ""),
    ],
)
def test_format_webserver(host: str, port: int, expected: str) -> None:
    assert format_webserver(host, port) == expected


def test_device_info_settings_reports_encryption_state() -> None:
    info = DeviceInfo()
    encrypted = device_info_settings(info, host="10.0.0.5", encrypted=True)
    plaintext = device_info_settings(info, host="10.0.0.5", encrypted=False)
    assert encrypted["encryption"] == "Configured"
    assert plaintext["encryption"] == "Not set"


def test_device_info_settings_maps_device_info_fields() -> None:
    info = DeviceInfo(
        name="garage",
        model="ESP32-S3",
        esphome_version="2026.7.0",
        project_name="Brand.AQ-1",
        project_version="1.2.3",
        webserver_port=80,
        has_deep_sleep=True,
    )
    settings = device_info_settings(info, host="10.0.0.5", encrypted=False)
    assert settings["hostname"] == "garage"
    assert settings["model"] == "ESP32-S3"
    assert settings["esphome_version"] == "2026.7.0"
    assert settings["project"] == "Brand.AQ-1 1.2.3"
    assert settings["webserver"] == "http://10.0.0.5:80"
    assert settings["deep_sleep"] == "Yes"


def test_device_info_settings_blanks_webserver_when_not_exposed() -> None:
    settings = device_info_settings(DeviceInfo(), host="10.0.0.5", encrypted=False)
    assert settings["webserver"] == ""
    assert settings["deep_sleep"] == "No"


def test_changed_values_keeps_only_differing_entries() -> None:
    current = {"model": "ESP32", "deep_sleep": "No", "port": 6053}
    values = {"model": "ESP32", "deep_sleep": "Yes", "port": 6053, "mac": "aa"}
    assert changed_values(current, values) == {"deep_sleep": "Yes", "mac": "aa"}


def test_changed_values_empty_when_nothing_changed() -> None:
    values = {"host": "10.0.0.5", "port": "6053"}
    assert changed_values(dict(values), values) == {}


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (InvalidEncryptionKeyAPIError("x"), "errors.invalid_encryption_key"),
        (RequiresEncryptionAPIError("x"), "errors.requires_encryption_key"),
        (InvalidAuthAPIError("x"), "errors.invalid_auth"),
        (EncryptionPlaintextAPIError("x"), "errors.encryption_plaintext"),
        (EncryptionHelloAPIError("x"), "errors.encryption_hello"),
        (
            BadMACAddressAPIError("x", "garage", "aa:bb:cc:dd:ee:ff"),
            "errors.device_mismatch",
        ),
        (BadNameAPIError("x", "garage"), "errors.device_mismatch"),
        (ResolveAPIError("x"), "errors.resolve_error"),
        (TimeoutAPIError("x"), "errors.timeout"),
        (HandshakeAPIError("x"), "errors.handshake"),
        (APIConnectionError("x"), "errors.cannot_connect"),
        (RuntimeError("x"), "errors.cannot_connect"),
    ],
)
def test_error_key(error: BaseException, expected: str) -> None:
    assert error_key(error) == expected


def test_error_key_checks_encryption_before_handshake() -> None:
    """Encryption failures subclass HandshakeAPIError, so order matters."""
    error = InvalidEncryptionKeyAPIError("x")
    assert isinstance(error, HandshakeAPIError)
    assert error_key(error) == "errors.invalid_encryption_key"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (RequiresEncryptionAPIError("x"), True),
        (InvalidEncryptionKeyAPIError("x"), True),
        (InvalidAuthAPIError("x"), False),
        (TimeoutAPIError("x"), False),
    ],
)
def test_needs_encryption_key(error: BaseException, expected: bool) -> None:
    assert needs_encryption_key(error) is expected


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (RequiresEncryptionAPIError("x"), True),
        (InvalidEncryptionKeyAPIError("x"), True),
        (InvalidAuthAPIError("x"), True),
        (EncryptionPlaintextAPIError("x"), True),
        (TimeoutAPIError("x"), False),
        (ResolveAPIError("x"), False),
        (APIConnectionError("x"), False),
    ],
)
def test_should_stop_reconnect(error: BaseException, expected: bool) -> None:
    """Retrying only helps for transient faults, never for bad credentials."""
    assert should_stop_reconnect(error) is expected


def test_error_predicates_are_specific() -> None:
    assert requires_encryption(RequiresEncryptionAPIError("x")) is True
    assert requires_encryption(InvalidEncryptionKeyAPIError("x")) is False
    assert invalid_encryption_key(InvalidEncryptionKeyAPIError("x")) is True
    assert is_device_mismatch(BadNameAPIError("x", "garage")) is True
    assert is_device_mismatch(TimeoutAPIError("x")) is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        ("TRUE", True),
        (" 1 ", True),
        ("false", False),
        ("0", False),
        (True, False),
        (1, False),
        (None, False),
    ],
)
def test_is_debug_enabled(
    homey_env: dict[str, object],
    value: object,
    expected: bool,
) -> None:
    """Only the strings ``true`` / ``1`` enable debug; booleans do not."""
    if value is not None:
        homey_env["DEBUG"] = value
    assert is_debug_enabled() is expected


def test_debug_log_is_silent_when_disabled(homey_env: dict[str, object]) -> None:
    calls: list[tuple[Any, ...]] = []
    debug_log(lambda *args: calls.append(args), "hello")
    assert calls == []


def test_debug_log_prefixes_when_enabled(homey_env: dict[str, object]) -> None:
    homey_env["DEBUG"] = "true"
    calls: list[tuple[Any, ...]] = []
    debug_log(lambda *args: calls.append(args), "hello", 42)
    assert calls == [("[dbg]", "hello", 42)]


def test_attach_library_logs_is_idempotent(
    homey_env: dict[str, object],
    reset_library_logs: None,
) -> None:
    """A second driver must not attach another stdlib handler."""
    logs: list[str] = []
    errors: list[str] = []
    attach_library_logs(logs.append, errors.append)
    attach_library_logs(logs.append, errors.append)

    logger = logging.getLogger("aioesphomeapi")
    handler_count = sum(
        1 for handler in logger.handlers if type(handler).__name__ == "_HomeyLogHandler"
    )
    assert handler_count == 1
    assert logger.level == logging.INFO

    logger.info("info-line")
    logger.warning("warn-line")
    assert logs == ["info-line"]
    assert errors == ["warn-line"]


def test_attach_library_logs_uses_debug_level_when_enabled(
    homey_env: dict[str, object],
    reset_library_logs: None,
) -> None:
    homey_env["DEBUG"] = "1"
    attach_library_logs(lambda *_: None, lambda *_: None)
    assert logging.getLogger("aioesphomeapi").level == logging.DEBUG
