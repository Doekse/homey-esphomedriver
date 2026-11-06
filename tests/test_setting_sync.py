"""Keeping a linked setting and its ESPHome entity in step at runtime.

The node is the truth for the value it holds, so reported states are mirrored
into the setting; the entity is written only when the user saves; a sleeping
node gets the write when it wakes.
"""

from __future__ import annotations

import asyncio
import copy
from types import MappingProxyType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, call

import pytest
from aioesphomeapi import NumberInfo, NumberState, SelectInfo, SelectState

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
    pass


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
        mirrored=[],
    )

    async def set_store_value(key: str, value: Any) -> None:
        saved[key] = copy.deepcopy(value)

    async def set_settings(values: dict[str, Any]) -> None:
        device.mirrored.append(dict(values))
        current.update(values)

    device.store = saved
    device.settings = current
    device.get_store = lambda: MappingProxyType(copy.deepcopy(saved))
    device.set_store_value = set_store_value
    device.get_setting = current.get
    device.set_settings = set_settings
    return device


async def _drain(sync: SettingEntitySync) -> None:
    for _ in range(5):
        await asyncio.sleep(0)
    task = sync._mirror_task
    if task is not None:
        await task


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

        # The connect dump still carries the old value; the queued edit wins.
        sync.on_state(NumberState(key=11, state=0.5))
        await _drain(sync)
        assert device.mirrored == []

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


def test_failing_converter_rejects_the_save() -> None:
    """A lookup-table converter raises KeyError, not ValueError."""

    async def run() -> None:
        device = _device()
        sync = SettingEntitySync(device)
        sync.register("mode", to_entity={"0": "eco", "1": "boost"}.__getitem__)
        with pytest.raises(ValueError, match="errors.setting_invalid"):
            await sync.on_settings({"mode": "2"}, ("mode",))
        device.client.command.assert_not_called()

    asyncio.run(run())


def test_queued_value_that_cannot_convert_does_not_block_the_rest() -> None:
    async def run() -> None:
        device = _device(
            store={
                "setting_entities": BINDINGS,
                "pending_settings": {"mode": "2", "offset": 1.5},
            }
        )
        sync = SettingEntitySync(device)
        sync.register("mode", to_entity={"0": "eco", "1": "boost"}.__getitem__)

        await sync.flush_pending()

        device.client.command.assert_called_once_with("number_command", 11, 1.5)
        assert device.store["pending_settings"] == {}
        device.error.assert_called_once()

    asyncio.run(run())


def test_reported_value_is_mirrored_into_the_setting() -> None:
    async def run() -> None:
        device = _device()
        sync = SettingEntitySync(device)
        sync.on_state(SelectState(key=12, state="boost"))
        sync.on_state(NumberState(key=11, state=0.0))  # already equal
        sync.on_state(NumberState(key=99, state=3.0))  # not linked
        await _drain(sync)
        assert device.mirrored == [{"mode": "boost"}]
        device.client.command.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize(
    "state",
    [
        NumberState(key=11, state=float("nan")),
        NumberState(key=11, state=2.0, missing_state=True),
        SelectState(key=12, state="", missing_state=True),
    ],
)
def test_placeholder_states_are_not_mirrored(state: Any) -> None:
    async def run() -> None:
        device = _device()
        sync = SettingEntitySync(device)
        sync.on_state(state)
        await _drain(sync)
        assert device.mirrored == []

    asyncio.run(run())


def test_mirror_keeps_only_the_latest_value() -> None:
    async def run() -> None:
        device = _device()
        sync = SettingEntitySync(device)
        sync.on_state(NumberState(key=11, state=1.0))
        sync.on_state(NumberState(key=11, state=2.0))
        await _drain(sync)
        assert device.mirrored == [{"offset": 2.0}]

    asyncio.run(run())


def test_echo_refused_during_a_save_is_dropped() -> None:
    """The SDK refuses set_settings while a save is pending. What the node
    reports then is the value being saved, which the save commits anyway."""

    async def run() -> None:
        device = _device()

        async def set_settings(values: dict[str, Any]) -> None:
            raise RuntimeError("Cannot set settings while on_settings is pending")

        device.set_settings = set_settings
        sync = SettingEntitySync(device)
        sync.on_state(NumberState(key=11, state=2.0))
        await _drain(sync)

        device.error.assert_not_called()
        assert "'offset'" in device.log.call_args.args[0]
        assert sync._mirror_queue == {}

    asyncio.run(run())


def test_rejected_mirror_does_not_hold_back_the_others() -> None:
    async def run() -> None:
        device = _device()

        async def set_settings(values: dict[str, Any]) -> None:
            if "offset" in values:
                raise ValueError("out of range")
            device.mirrored.append(dict(values))

        device.set_settings = set_settings
        sync = SettingEntitySync(device)
        sync.on_state(NumberState(key=11, state=99.0))
        sync.on_state(SelectState(key=12, state="boost"))
        await _drain(sync)

        assert device.mirrored == [{"mode": "boost"}]
        device.log.assert_called_once()
        assert "'offset'" in device.log.call_args.args[0]

    asyncio.run(run())


def test_registered_converters_run_both_ways() -> None:
    async def run() -> None:
        device = _device()
        sync = SettingEntitySync(device)
        sync.register(
            "offset", to_entity=lambda value: value * 10, to_setting=lambda v: v / 10
        )

        await sync.on_settings({"offset": 1.5}, ("offset",))
        device.client.command.assert_called_once_with("number_command", 11, 15.0)

        sync.on_state(NumberState(key=11, state=20.0))
        await _drain(sync)
        assert device.mirrored == [{"offset": 2.0}]

    asyncio.run(run())


def test_new_bindings_mirror_states_seen_before_binding() -> None:
    """A device paired before its driver linked the setting still picks up the
    value from the connect dump, even while its old capability takes it too."""

    async def run() -> None:
        device = _device(store={})
        sync = SettingEntitySync(device)
        sync.on_state(NumberState(key=11, state=3.0))  # not bound yet
        listed = MagicMock()

        async def list_entities_services() -> tuple[list[Any], list[Any]]:
            listed()
            return [OFFSET, MODE], []

        client = SimpleNamespace(list_entities_services=list_entities_services)
        await sync.ensure_bindings(client)
        await sync.ensure_bindings(client)
        await _drain(sync)

        listed.assert_called_once()
        assert device.store["setting_entities"] == BINDINGS
        assert device.mirrored == [{"offset": 3.0}]

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


def test_converters_are_per_setting() -> None:
    """A converter on one setting leaves the others passing through."""

    async def run() -> None:
        device = _device()
        sync = SettingEntitySync(device)
        sync.register("mode", to_entity=str.upper, to_setting=str.lower)

        await sync.on_settings({"offset": 1.5, "mode": "boost"}, ("offset", "mode"))
        assert device.client.command.call_args_list == [
            call("number_command", 11, 1.5),
            call("select_command", 12, "BOOST"),
        ]

    asyncio.run(run())


def test_registering_an_unlinked_setting_fails() -> None:
    sync = SettingEntitySync(_device())
    with pytest.raises(ValueError, match="'offest' is not linked"):
        sync.register("offest", to_entity=float)
