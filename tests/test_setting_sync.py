"""Writing a linked setting to its ESPHome entity at runtime.

The entity is written when the user saves; a sleeping node gets the write
when it wakes.
"""

from __future__ import annotations

import asyncio
import copy
from types import MappingProxyType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from aioesphomeapi import NumberInfo, SelectInfo

from homey_esphomedriver.bindings import CapabilityBindings
from homey_esphomedriver.profile import BrandProfile
from homey_esphomedriver.settings import SettingEntitySync
from homey_esphomedriver.settings.links import SettingEntity

OFFSET = NumberInfo(object_id="temp_offset", key=11, name="Offset")
MODE = SelectInfo(object_id="mode", key=12, name="Mode", options=["eco", "boost"])

LINKS = {
    "offset": SettingEntity("number", "Offset"),
    "mode": SettingEntity("select", "Mode"),
}


class _Device(SimpleNamespace):
    pass


def _device(
    *,
    available: bool = True,
    deep_sleep: bool = False,
    store: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
    entities: list[Any] | None = None,
) -> _Device:
    saved = {} if store is None else store
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
    device._bindings = CapabilityBindings(device)  # type: ignore[arg-type]
    device._bindings.bind([OFFSET, MODE] if entities is None else entities)
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
        device = _device(store={"pending_settings": {"mode": "boost"}})
        await SettingEntitySync(device).flush_pending()
        device.client.command.assert_called_once_with("select_command", 12, "boost")

    asyncio.run(run())


def test_queued_value_that_cannot_convert_does_not_block_the_rest() -> None:
    async def run() -> None:
        device = _device(store={"pending_settings": {"offset": "abc", "mode": "boost"}})
        sync = SettingEntitySync(device)

        await sync.flush_pending()

        device.client.command.assert_called_once_with("select_command", 12, "boost")
        assert device.store["pending_settings"] == {}
        device.error.assert_called_once()

    asyncio.run(run())


def test_setting_without_its_entity_saves_in_homey_only() -> None:
    async def run() -> None:
        device = _device(entities=[OFFSET])
        sync = SettingEntitySync(device)
        assert await sync.on_settings({"mode": "boost"}, ("mode",)) is None
        device.client.command.assert_not_called()
        assert "'mode'" in device.log.call_args.args[0]

    asyncio.run(run())


def test_queued_settings_the_driver_dropped_are_ignored() -> None:
    async def run() -> None:
        device = _device(store={"pending_settings": {"old": True, "offset": 1.5}})
        await SettingEntitySync(device).flush_pending()
        device.client.command.assert_called_once_with("number_command", 11, 1.5)

    asyncio.run(run())


def test_sub_device_entity_is_written_with_its_device_id() -> None:
    async def run() -> None:
        sub = NumberInfo(object_id="offset", key=11, name="Offset", device_id=4)
        device = _device(entities=[sub])
        device.brand_profile = BrandProfile(
            setting_entities={"offset": SettingEntity("number", "Offset", 4)}
        )
        sync = SettingEntitySync(device)
        await sync.on_settings({"offset": 1.5}, ("offset",))
        device.client.command.assert_called_once_with(
            "number_command", 11, 1.5, device_id=4
        )

    asyncio.run(run())
