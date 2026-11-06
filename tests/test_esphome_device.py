"""Capability sync when a node reconnects with a new compilation time."""

from __future__ import annotations

import asyncio
import copy
from types import MappingProxyType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aioesphomeapi import (
    APIConnectionError,
    DeviceInfo,
    EntityInfo,
    NumberInfo,
    NumberState,
    SwitchInfo,
)

from homey_esphomedriver.capabilities import DeviceCapabilityHandler, EntitySyncResult
from homey_esphomedriver.entities.mapping import DeviceEntityMapper
from homey_esphomedriver.esphome_client import EspHomeClient, SessionState
from homey_esphomedriver.esphome_device import EspHomeDevice, _notification_tasks
from homey_esphomedriver.esphome_util import device_info_settings
from homey_esphomedriver.profile import DEFAULT_BRAND_PROFILE, BrandProfile
from homey_esphomedriver.settings import SettingEntitySync
from homey_esphomedriver.settings.links import SettingEntity


def _mapped(*entities: EntityInfo) -> tuple[list[str], dict[str, Any]]:
    scratch = DeviceEntityMapper.empty_option()
    DeviceEntityMapper.map_device(list(entities), scratch)
    return list(scratch["capabilities"]), dict(scratch["capabilitiesOptions"])


def _device(
    *,
    store: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
    profile: BrandProfile | None = None,
    capabilities: list[str] | None = None,
    options: dict[str, Any] | None = None,
) -> EspHomeDevice:
    device = EspHomeDevice.__new__(EspHomeDevice)
    device._store = {} if store is None else dict(store)
    device._settings = {} if settings is None else dict(settings)
    device._pending_build = None
    device._capabilities = list(capabilities or [])
    device._capabilities_options = dict(options or {})
    device._state = {}
    device._commands = SimpleNamespace(
        register_listener_for_capability=MagicMock(),
        register_multi_listeners=MagicMock(),
    )
    device._state_handler = SimpleNamespace(init=AsyncMock())
    device._capability_handler = DeviceCapabilityHandler(device)
    device.driver = SimpleNamespace(brand_profile=profile or DEFAULT_BRAND_PROFILE)
    device._name = "node"
    device.timeouts: list[Any] = []
    device.warnings: list[str] = []
    device.store_writes: list[tuple[str, Any]] = []
    device.homey = SimpleNamespace(
        translate=lambda key, **tags: f"{key}:{next(iter(tags.values()), '')}",
        set_timeout=lambda callback, _ms: device.timeouts.append(callback),
        notifications=SimpleNamespace(create_notification=AsyncMock()),
    )
    device.set_warning = AsyncMock(
        side_effect=lambda message: device.warnings.append(message)
    )
    device.set_unavailable = AsyncMock()
    device.set_available = AsyncMock()
    device.set_class = AsyncMock()
    device.set_capability_options = AsyncMock()
    device.log = MagicMock()
    device.error = MagicMock()
    device._client_emit = AsyncMock()

    def get_store() -> MappingProxyType[str, Any]:
        return MappingProxyType(copy.deepcopy(device._store))

    def get_settings() -> MappingProxyType[str, Any]:
        return MappingProxyType(copy.deepcopy(device._settings))

    async def set_store_value(key: str, value: Any) -> None:
        device._store[key] = copy.deepcopy(value)
        device.store_writes.append((key, value))

    async def set_settings(values: dict[str, Any]) -> None:
        device._settings.update(values)

    device.get_store = get_store  # type: ignore[method-assign]
    device.get_settings = get_settings  # type: ignore[method-assign]
    device.get_setting = lambda key: device._settings.get(key)  # type: ignore[method-assign]
    device.set_store_value = set_store_value  # type: ignore[method-assign]
    device.set_settings = set_settings  # type: ignore[method-assign]
    device._setting_sync = SettingEntitySync(device)
    return device


def _info(build: str, *, project: str = "") -> DeviceInfo:
    return DeviceInfo(name="node", compilation_time=build, project_name=project)


async def _login(
    device: EspHomeDevice,
    info: DeviceInfo,
    list_entities: Any = None,
) -> tuple[EspHomeClient, list[tuple[str, SessionState]]]:
    events: list[tuple[str, SessionState]] = []

    async def on_connected(device_info: DeviceInfo) -> None:
        await device._on_connected(device_info)
        events.append(("connected", client.state))

    client = EspHomeClient(
        "192.0.2.1",
        on_connected=on_connected,
        on_disconnected=device._on_disconnected,
        on_ready=device._on_ready,
    )
    device._client = client
    client._on_state = AsyncMock()
    client._reconnect = MagicMock()
    api = MagicMock()
    api.device_info = AsyncMock(return_value=info)

    async def listed() -> tuple[list[EntityInfo], list[object]]:
        events.append(("list", client.state))
        if list_entities is not None:
            return await list_entities()
        return [], []

    api.list_entities_services = listed
    client._cli = api
    await client._handle_connect()
    await asyncio.sleep(0)
    return client, events


def test_deep_sleep_stays_available_only_after_a_clean_goodbye() -> None:
    """Last state after a clean sleep; unavailable on a drop or failed dial."""
    device = _device()
    device._client = EspHomeClient("192.0.2.1", deep_sleep=True)

    async def run() -> None:
        await device._on_disconnected(True)
        device.set_unavailable.assert_not_awaited()

        await device._on_disconnected(False)
        device.set_unavailable.assert_awaited_with("errors.connection_lost:")

        device.set_unavailable.reset_mock()
        await device._on_connect_error(APIConnectionError("refused"))
        device.set_unavailable.assert_awaited_with("errors.cannot_connect:")

    asyncio.run(run())


def test_unchanged_build_does_not_list_or_write_store() -> None:
    info = _info("build-1")
    device = _device(
        store={"entities_build": "build-1"},
        settings=dict(device_info_settings(info, host="192.0.2.1", encrypted=False)),
    )

    async def run() -> None:
        _client, events = await _login(device, info)
        assert events == [("connected", SessionState.CONNECTED)]
        assert device.store_writes == []
        assert device._pending_build is None

    asyncio.run(run())


def test_changed_build_syncs_only_after_ready() -> None:
    relay = SwitchInfo(object_id="relay", key=1, name="Relay")
    pump = SwitchInfo(object_id="pump", key=2, name="Pump")
    capabilities, options = _mapped(relay)
    device = _device(
        store={"entities_build": "old"},
        capabilities=capabilities,
        options=options,
    )

    async def entities() -> tuple[list[EntityInfo], list[object]]:
        return [relay, pump], []

    async def run() -> None:
        _client, events = await _login(device, _info("new"), entities)
        assert events[0] == ("connected", SessionState.CONNECTED)
        assert ("list", SessionState.READY) in events
        assert any(name == "list" for name, _state in events)
        assert events.index(("connected", SessionState.CONNECTED)) < events.index(
            ("list", SessionState.READY)
        )
        assert device._store["entities_build"] == "new"
        assert device.store_writes[-1] == ("entities_build", "new")
        assert device.set_class.await_count == 0
        added = [cap for cap in device._capabilities if cap not in capabilities]
        assert added
        assert "onoff" in device._capabilities

    asyncio.run(run())


def test_changed_build_keeps_entities_build_when_sync_fails() -> None:
    device = _device(store={"entities_build": "old"})

    async def entities() -> tuple[list[EntityInfo], list[object]]:
        raise RuntimeError("list failed")

    async def run() -> None:
        _client, events = await _login(device, _info("new"), entities)
        assert ("list", SessionState.READY) in events
        assert device._store["entities_build"] == "old"
        assert device.store_writes == []

    asyncio.run(run())


def test_missing_entities_build_seeds_old_setting_without_sync() -> None:
    device = _device(settings={"compilation_time": "build-1"})

    async def run() -> None:
        _client, events = await _login(device, _info("build-1"))
        assert device.store_writes == [("entities_build", "build-1")]
        assert device._store["entities_build"] == "build-1"
        assert not any(name == "list" for name, _state in events)

    asyncio.run(run())


def test_missing_entities_build_seeds_old_setting_before_a_real_change() -> None:
    """A driver upgrade still syncs when the node was reflashed while offline."""
    device = _device(settings={"compilation_time": "old"})

    async def run() -> None:
        _client, events = await _login(device, _info("new"))
        assert events[0] == ("connected", SessionState.CONNECTED)
        assert device.store_writes[0] == ("entities_build", "old")
        assert ("list", SessionState.READY) in events
        assert device.store_writes[-1] == ("entities_build", "new")

    asyncio.run(run())


def test_disconnect_during_sync_leaves_entities_build() -> None:
    device = _device(store={"entities_build": "old"})
    started = asyncio.Event()

    async def entities() -> tuple[list[EntityInfo], list[object]]:
        started.set()
        await asyncio.Event().wait()
        return [], []

    async def run() -> None:
        client, _events = await _login(device, _info("new"), entities)
        await started.wait()
        task = client._ready_task
        assert task is not None
        await client._handle_disconnect(expected_disconnect=False)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()
        assert device._store["entities_build"] == "old"
        assert ("entities_build", "new") not in device.store_writes

    asyncio.run(run())


def test_project_mismatch_warns_without_sync() -> None:
    device = _device(
        store={"entities_build": "old"},
        profile=BrandProfile(projects=frozenset({"allowed.project"})),
    )

    async def run() -> None:
        _client, events = await _login(device, _info("new", project="other.project"))
        assert device._pending_build is None
        assert not any(name == "list" for name, _state in events)
        for callback in device.timeouts:
            callback()
        await asyncio.sleep(0)
        assert device.warnings == ["warnings.project_mismatch:other.project"]

    asyncio.run(run())


def test_project_mismatch_keeps_native_app_warning() -> None:
    device = _device(
        store={"entities_build": "old"},
        profile=BrandProfile(
            projects=frozenset({"allowed.project"}),
            native_apps={"other.project": "Native App"},
        ),
    )

    async def run() -> None:
        _client, events = await _login(device, _info("new", project="other.project"))
        assert not any(name == "list" for name, _state in events)
        for callback in device.timeouts:
            callback()
        await asyncio.sleep(0)
        assert device.warnings == ["nativeAppSuggestion:Native App"]

    asyncio.run(run())


def _arm_entity_sync(device: EspHomeDevice) -> None:
    device._pending_build = "new"
    device._capability_handler.sync_entities = AsyncMock(  # type: ignore[method-assign]
        return_value=EntitySyncResult(
            added=["onoff.pump"],
            removed=["onoff.relay"],
            removed_titles=["Relay"],
        )
    )


async def _finish_sync(device: EspHomeDevice) -> None:
    await device._sync_if_rebuilt()
    await asyncio.gather(*tuple(_notification_tasks))


def test_sync_if_rebuilt_logs_notification_failure() -> None:
    """A timeline failure is logged and does not fail the firmware sync."""
    device = _device()
    error = RuntimeError("boom")
    device.homey.notifications.create_notification = AsyncMock(side_effect=error)
    _arm_entity_sync(device)

    asyncio.run(_finish_sync(device))

    device.error.assert_called_once_with(
        "Failed to create entities changed notification:",
        error,
    )


def test_sync_if_rebuilt_notifies_when_setting_missing() -> None:
    """Devices paired before the checkbox existed stay opted in."""
    device = _device()
    assert device.get_setting("notify_entities_changed") is None
    _arm_entity_sync(device)

    asyncio.run(_finish_sync(device))

    device.homey.notifications.create_notification.assert_awaited_once_with(
        "notifications.entities_changed_removed:**node**"
    )


def test_sync_if_rebuilt_skips_notification_when_disabled() -> None:
    device = _device(settings={"notify_entities_changed": False})
    _arm_entity_sync(device)

    asyncio.run(_finish_sync(device))

    device.homey.notifications.create_notification.assert_not_awaited()


def test_rejected_linked_setting_applies_nothing_else() -> None:
    """Homey keeps the old values of a rejected save, so nothing may change."""
    device = _device(
        store={"setting_entities": {"offset": {"key": 11, "domain": "number"}}},
        profile=BrandProfile(
            setting_entities={"offset": SettingEntity("temp_offset", "number")}
        ),
    )
    device._capability_handler = SimpleNamespace(apply_category=AsyncMock())  # type: ignore[assignment]

    with pytest.raises(ValueError, match="errors.setting_invalid"):
        asyncio.run(
            device.on_settings(
                {},
                {"offset": "abc", "show_diagnostics": True},
                ("offset", "show_diagnostics"),
            )
        )

    device._capability_handler.apply_category.assert_not_awaited()


def test_ready_writes_settings_queued_while_the_node_slept() -> None:
    """A deep-sleep node gets the settings saved while it slept as it wakes."""
    offset = NumberInfo(object_id="temp_offset", key=11, name="Offset")
    info = _info("build-1")
    device = _device(
        store={
            "entities_build": "build-1",
            "setting_entities": {"offset": {"key": 11, "domain": "number"}},
            "pending_settings": {"offset": 1.5},
        },
        settings=dict(device_info_settings(info, host="192.0.2.1", encrypted=False)),
        profile=BrandProfile(
            setting_entities={"offset": SettingEntity("temp_offset", "number")}
        ),
    )

    async def entities() -> tuple[list[EntityInfo], list[object]]:
        return [offset], []

    async def run() -> None:
        client, _events = await _login(device, info, entities)
        for _ in range(3):
            await asyncio.sleep(0)
        client.api.number_command.assert_called_once_with(11, 1.5)
        assert device._store["pending_settings"] == {}

    asyncio.run(run())


def test_driver_update_link_seeds_the_setting_from_the_connect_dump() -> None:
    """The entity still has its tile capability until Refresh; the setting
    the driver update linked to it starts from the value the node reported."""
    offset = NumberInfo(object_id="temp_offset", key=11, name="Offset")
    capabilities, options = _mapped(offset)
    info = _info("build-1")
    device = _device(
        store={"entities_build": "build-1"},
        settings={
            **device_info_settings(info, host="192.0.2.1", encrypted=False),
            "offset": 0.0,
        },
        profile=BrandProfile(
            setting_entities={"offset": SettingEntity("temp_offset", "number")}
        ),
        capabilities=capabilities,
        options=options,
    )
    device._state_handler = SimpleNamespace(handle_state=MagicMock())  # type: ignore[assignment]

    async def entities() -> tuple[list[EntityInfo], list[object]]:
        return [offset], []

    async def run() -> None:
        # The connect dump reaches the tile before the link is bound.
        device._on_state(NumberState(key=11, state=3.0))
        await _login(device, info, entities)
        for _ in range(5):
            await asyncio.sleep(0)
        assert device._store["setting_entities"] == {
            "offset": {"key": 11, "domain": "number"}
        }
        assert device._settings["offset"] == 3.0
        device._state_handler.handle_state.assert_called_once()

    asyncio.run(run())


def test_on_init_starts_the_client_after_brand_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Converters from on_esphome_init must see the connect dump and queued writes."""
    events: list[str] = []

    class _Sync:
        def __init__(self, _device: Any) -> None:
            events.append("sync")

        def register(self, setting_id: str, **_converters: Any) -> None:
            events.append(f"register {setting_id}")

    class _Handler:
        def __init__(self, _device: Any) -> None:
            pass

        async def init(self) -> None:
            return None

        async def ensure(self) -> None:
            return None

    class _Client:
        async def start(self, _on_state: Any) -> None:
            events.append("client started")

    module = "homey_esphomedriver.esphome_device"
    monkeypatch.setattr(f"{module}.SettingEntitySync", _Sync)
    for name in (
        "DeviceEntityStateHandler",
        "DeviceEntityCommandHandler",
        "DeviceCapabilityHandler",
    ):
        monkeypatch.setattr(f"{module}.{name}", _Handler)
    monkeypatch.setattr(EspHomeDevice.__mro__[1], "on_init", AsyncMock(), raising=False)

    class _Brand(EspHomeDevice):
        async def on_esphome_init(self, client: Any) -> None:
            self.register_setting("temp_offset", to_setting=float)

    device = _device(store={"address": "192.0.2.1"})
    device.__class__ = _Brand
    device.get_data = lambda: {"id": "aabbccddeeff"}  # type: ignore[method-assign]

    def create() -> _Client:
        events.append("client created")
        return _Client()

    device._create_client = create  # type: ignore[method-assign,assignment]

    asyncio.run(device.on_init())

    assert events == [
        "sync",
        "client created",
        "register temp_offset",
        "client started",
    ]
