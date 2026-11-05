"""Writing a linked setting to its ESPHome entity at runtime.

The entity is written only when the user saves; an invalid value or an offline
mains node rejects the save; a sleeping node gets the write when it wakes.
"""

from __future__ import annotations

import asyncio
import copy
from types import MappingProxyType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from aioesphomeapi import NumberInfo, SelectInfo

from homey_esphomedriver.profile import BrandProfile
from homey_esphomedriver.settings import SettingEntitySync
from homey_esphomedriver.settings.links import SettingEntity

OFFSET = NumberInfo(object_id="temp_offset", key=11, name="Offset")
MODE = SelectInfo(object_id="mode", key=12, name="Mode", options=["eco", "boost"])

LINKS = {
    "offset": SettingEntity("temp_offset", "number"),
    "mode": SettingEntity("mode", "dropdown"),
}
BINDINGS = {
    "offset": {"key": 11, "domain": "number"},
    "mode": {"key": 12, "domain": "select"},
}


class _Device(SimpleNamespace):
    def setting_to_entity(self, setting_id: str, value: Any) -> Any:
        return value


def _device(
    *,
    available: bool = True,
    deep_sleep: bool = False,
    store: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> _Device:
    saved = {"setting_entities": BINDINGS} if store is None else store
    current = {"offset": 0.0, "mode": "eco"} if settings is None else settings
    device = _Device(
        brand_profile=BrandProfile(setting_entities=LINKS),
        client=SimpleNamespace(
            available=available, deep_sleep=deep_sleep, command=MagicMock()
        ),
        homey=SimpleNamespace(translate=lambda key: key),
        log=MagicMock(),
        error=MagicMock(),
    )

    async def set_store_value(key: str, value: Any) -> None:
        saved[key] = copy.deepcopy(value)

    device.store = saved
    device.settings = current
    device.get_store = lambda: MappingProxyType(copy.deepcopy(saved))
    device.set_store_value = set_store_value
    device.get_setting = current.get
    return device


def test_save_writes_only_changed_linked_settings() -> None:
    async def run() -> None:
        device = _device()
        sync = SettingEntitySync(device)
        message = await sync.on_settings(
            {"offset": 1.5, "mode": "eco", "host": "x"}, ("offset", "host")
        )
        assert message is None
        device.client.command.assert_called_once_with("number_command", 11, 1.5)

    asyncio.run(run())


def test_invalid_value_rejects_the_save_before_any_write() -> None:
    async def run() -> None:
        device = _device()
        sync = SettingEntitySync(device)
        with pytest.raises(ValueError, match="errors.setting_invalid"):
            await sync.on_settings(
                {"offset": "abc", "mode": "boost"}, ("mode", "offset")
            )
        device.client.command.assert_not_called()

    asyncio.run(run())


def test_offline_mains_node_rejects_the_save() -> None:
    async def run() -> None:
        sync = SettingEntitySync(_device(available=False))
        with pytest.raises(RuntimeError, match="errors.device_not_connected"):
            await sync.on_settings({"offset": 1.5}, ("offset",))

    asyncio.run(run())


def test_sleeping_node_queues_the_write_until_it_wakes() -> None:
    async def run() -> None:
        device = _device(available=False, deep_sleep=True)
        sync = SettingEntitySync(device)

        message = await sync.on_settings({"offset": 1.5}, ("offset",))

        assert message == "settings.applied_on_wake"
        assert device.store["pending_settings"] == {"offset": 1.5}
        device.client.command.assert_not_called()

        device.client.available = True
        await sync.flush_pending()
        device.client.command.assert_called_once_with("number_command", 11, 1.5)
        assert device.store["pending_settings"] == {}

    asyncio.run(run())


def test_queued_writes_survive_a_restart() -> None:
    async def run() -> None:
        device = _device(
            store={"setting_entities": BINDINGS, "pending_settings": {"mode": "boost"}}
        )
        await SettingEntitySync(device).flush_pending()
        device.client.command.assert_called_once_with("select_command", 12, "boost")

    asyncio.run(run())


def test_setting_to_entity_converts_before_the_write() -> None:
    async def run() -> None:
        device = _device()
        device.setting_to_entity = lambda _id, value: value * 10
        sync = SettingEntitySync(device)

        await sync.on_settings({"offset": 1.5}, ("offset",))
        device.client.command.assert_called_once_with("number_command", 11, 15.0)

    asyncio.run(run())


def test_settings_linked_after_pairing_are_bound_once() -> None:
    """A device paired before its driver linked the setting is bound on wake."""

    async def run() -> None:
        device = _device(store={})
        sync = SettingEntitySync(device)
        listed = MagicMock()

        async def list_entities_services() -> tuple[list[Any], list[Any]]:
            listed()
            return [OFFSET, MODE], []

        client = SimpleNamespace(list_entities_services=list_entities_services)
        await sync.ensure_bindings(client)
        await sync.ensure_bindings(client)

        listed.assert_called_once()
        assert device.store["setting_entities"] == BINDINGS

    asyncio.run(run())


def test_failed_listing_is_tried_again_next_session() -> None:
    """A node that drops during the listing has not been checked yet."""

    async def run() -> None:
        device = _device(store={})
        sync = SettingEntitySync(device)
        attempts: list[int] = []

        async def list_entities_services() -> tuple[list[Any], list[Any]]:
            attempts.append(1)
            if len(attempts) == 1:
                raise ConnectionError("node went back to sleep")
            return [OFFSET, MODE], []

        client = SimpleNamespace(list_entities_services=list_entities_services)
        with pytest.raises(ConnectionError):
            await sync.ensure_bindings(client)
        await sync.ensure_bindings(client)

        assert len(attempts) == 2
        assert device.store["setting_entities"] == BINDINGS

    asyncio.run(run())


def test_link_without_entity_is_not_looked_up_again() -> None:
    """The unbound outcome is stored, so a restart does not list again either."""

    async def run() -> None:
        device = _device(store={})
        listed = MagicMock()

        async def list_entities_services() -> tuple[list[Any], list[Any]]:
            listed()
            return [OFFSET], []

        client = SimpleNamespace(list_entities_services=list_entities_services)
        await SettingEntitySync(device).ensure_bindings(client)
        assert device.store["setting_entities"] == {
            "offset": BINDINGS["offset"],
            "mode": None,
        }

        restarted = SettingEntitySync(device)
        await restarted.ensure_bindings(client)
        listed.assert_called_once()
        await restarted.on_settings({"mode": "boost"}, ("mode",))
        device.client.command.assert_not_called()

    asyncio.run(run())


def test_bindings_for_settings_the_driver_dropped_are_ignored() -> None:
    async def run() -> None:
        device = _device(
            store={
                "setting_entities": {
                    **BINDINGS,
                    "old": {"key": 13, "domain": "switch"},
                }
            }
        )
        sync = SettingEntitySync(device)
        await sync.on_settings({"old": True}, ("old",))
        device.client.command.assert_not_called()

    asyncio.run(run())
