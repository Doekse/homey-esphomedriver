"""EspHomeDevice lifecycle: connect, bindings, linked settings and warnings."""

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
    SwitchState,
)

from homey_esphomedriver.bindings import CapabilityBindings
from homey_esphomedriver.esphome_client import EspHomeClient, SessionState
from homey_esphomedriver.esphome_device import EspHomeDevice
from homey_esphomedriver.esphome_util import device_info_settings
from homey_esphomedriver.profile import DEFAULT_BRAND_PROFILE, BrandProfile
from homey_esphomedriver.settings import SettingEntitySync
from homey_esphomedriver.settings.links import SettingEntity

OFFSET = NumberInfo(object_id="temp_offset", key=11, name="Offset")
RELAY = SwitchInfo(object_id="relay", key=1, name="Relay")
OFFSET_LINK = {"offset": SettingEntity("number", "Offset")}


def _device(
    *,
    store: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
    profile: BrandProfile | None = None,
    capabilities: list[str] | None = None,
) -> EspHomeDevice:
    device = EspHomeDevice.__new__(EspHomeDevice)
    device._store = {} if store is None else dict(store)
    device._settings = {} if settings is None else dict(settings)
    device._capabilities = list(capabilities or [])
    device._state = {}
    device._capability_listeners = {}
    device.driver = SimpleNamespace(brand_profile=profile or DEFAULT_BRAND_PROFILE)
    device._name = "node"
    device._client = None
    device.timeouts: list[Any] = []
    device.warnings: list[str] = []
    device.store_writes: list[tuple[str, Any]] = []
    device.values: list[tuple[str, Any]] = []
    device.homey = SimpleNamespace(
        translate=lambda key, **tags: f"{key}:{next(iter(tags.values()), '')}",
        set_timeout=lambda callback, _ms: device.timeouts.append(callback),
    )
    device.set_warning = AsyncMock(
        side_effect=lambda message: device.warnings.append(message)
    )
    device.set_unavailable = AsyncMock()
    device.set_available = AsyncMock()
    device.log = MagicMock()
    device.error = MagicMock()

    def get_store() -> MappingProxyType[str, Any]:
        return MappingProxyType(copy.deepcopy(device._store))

    def get_settings() -> MappingProxyType[str, Any]:
        return MappingProxyType(copy.deepcopy(device._settings))

    async def set_store_value(key: str, value: Any) -> None:
        device._store[key] = copy.deepcopy(value)
        device.store_writes.append((key, value))

    async def set_settings(values: dict[str, Any]) -> None:
        device._settings.update(values)

    async def set_capability_value(capability_id: str, value: Any) -> None:
        device.values.append((capability_id, value))

    def register_capability_listener(capability_id: str, listener: Any) -> None:
        device._capability_listeners[capability_id] = listener

    device.get_store = get_store  # type: ignore[method-assign]
    device.get_settings = get_settings  # type: ignore[method-assign]
    device.get_setting = lambda key: device._settings.get(key)  # type: ignore[method-assign]
    device.set_store_value = set_store_value  # type: ignore[method-assign]
    device.set_settings = set_settings  # type: ignore[method-assign]
    device.has_capability = lambda cap: cap in device._capabilities  # type: ignore[method-assign]
    device.set_capability_value = set_capability_value  # type: ignore[method-assign]
    device.register_capability_listener = register_capability_listener  # type: ignore[method-assign]
    device._bindings = CapabilityBindings(device)
    device._setting_sync = SettingEntitySync(device)
    return device


def _info(*, project: str = "") -> DeviceInfo:
    return DeviceInfo(name="node", compilation_time="build-1", project_name=project)


async def _login(
    device: EspHomeDevice,
    info: DeviceInfo,
    entities: list[EntityInfo] | None = None,
) -> tuple[EspHomeClient, list[str]]:
    events: list[str] = []

    def on_entities(listed: list[EntityInfo]) -> None:
        events.append("entities")
        device._bindings.bind(listed)

    async def on_connected(device_info: DeviceInfo) -> None:
        await device._on_connected(device_info)
        events.append(f"connected {client.state.name}")

    client = EspHomeClient(
        "192.0.2.1",
        on_entities=on_entities,
        on_connected=on_connected,
        on_disconnected=device._on_disconnected,
        on_ready=device._on_ready,
    )
    device._client = client
    client._on_state = device._on_state
    client._reconnect = MagicMock()
    api = MagicMock()
    api.device_info_and_list_entities = AsyncMock(
        return_value=(info, list(entities or []), [])
    )
    api.subscribe_states = MagicMock(side_effect=lambda _cb: events.append("subscribe"))
    client._cli = api
    await client._handle_connect()
    for _ in range(3):
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


def test_login_binds_entities_before_subscribing() -> None:
    """The connect dump reaches capabilities registered before the login."""
    device = _device(capabilities=["onoff"])
    device.register_capability("onoff", "switch", "Relay")

    async def run() -> None:
        client, events = await _login(device, _info(), [RELAY])
        assert events[:2] == ["entities", "subscribe"]
        assert client.state is SessionState.READY
        device._on_state(SwitchState(key=1, state=True))
        await asyncio.sleep(0)
        assert device.values == [("onoff", True)]

    asyncio.run(run())


def test_capability_listener_sends_the_entity_command() -> None:
    device = _device(capabilities=["onoff"])
    device.register_capability("onoff", "switch", "Relay")

    async def run() -> None:
        client, _events = await _login(device, _info(), [RELAY])
        await device._capability_listeners["onoff"](False)
        client.api.switch_command.assert_called_once_with(1, state=False)

    asyncio.run(run())


def test_project_mismatch_warns() -> None:
    device = _device(profile=BrandProfile(projects=frozenset({"allowed.project"})))

    async def run() -> None:
        await _login(device, _info(project="other.project"))
        for callback in device.timeouts:
            callback()
        await asyncio.sleep(0)
        assert device.warnings == ["warnings.project_mismatch:other.project"]

    asyncio.run(run())


def test_project_mismatch_keeps_native_app_warning() -> None:
    device = _device(
        profile=BrandProfile(
            projects=frozenset({"allowed.project"}),
            native_apps={"other.project": "Native App"},
        ),
    )

    async def run() -> None:
        await _login(device, _info(project="other.project"))
        for callback in device.timeouts:
            callback()
        await asyncio.sleep(0)
        assert device.warnings == ["nativeAppSuggestion:Native App"]

    asyncio.run(run())


def test_rejected_linked_setting_raises() -> None:
    """Homey keeps the old values of a rejected save."""
    device = _device(profile=BrandProfile(setting_entities=OFFSET_LINK))

    with pytest.raises(ValueError, match="errors.setting_invalid"):
        asyncio.run(device.on_settings({}, {"offset": "abc"}, ("offset",)))


def test_ready_writes_settings_queued_while_the_node_slept() -> None:
    """A deep-sleep node gets the settings saved while it slept as it wakes."""
    info = _info()
    device = _device(
        store={"pending_settings": {"offset": 1.5}},
        settings=dict(device_info_settings(info, host="192.0.2.1", encrypted=False)),
        profile=BrandProfile(setting_entities=OFFSET_LINK),
    )

    async def run() -> None:
        client, _events = await _login(device, info, [OFFSET])
        client.api.number_command.assert_called_once_with(11, 1.5)
        assert device._store["pending_settings"] == {}

    asyncio.run(run())


def test_connect_dump_mirrors_into_a_linked_setting() -> None:
    info = _info()
    device = _device(
        settings={
            **device_info_settings(info, host="192.0.2.1", encrypted=False),
            "offset": 0.0,
        },
        profile=BrandProfile(setting_entities=OFFSET_LINK),
    )

    async def run() -> None:
        await _login(device, info, [OFFSET])
        device._on_state(NumberState(key=11, state=3.0))
        for _ in range(3):
            await asyncio.sleep(0)
        assert device._settings["offset"] == 3.0

    asyncio.run(run())


def test_on_init_starts_the_client_after_brand_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bindings from on_esphome_init must see the connect dump and queued writes."""
    events: list[str] = []

    class _Sync:
        def __init__(self, _device: Any) -> None:
            events.append("sync")

        def register(self, setting_id: str, **_converters: Any) -> None:
            events.append(f"register {setting_id}")

    class _Client:
        async def start(self, _on_state: Any) -> None:
            events.append("client started")

    module = "homey_esphomedriver.esphome_device"
    monkeypatch.setattr(f"{module}.SettingEntitySync", _Sync)
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
