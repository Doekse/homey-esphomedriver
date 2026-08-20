"""Runtime Homey device backed by one ESPHome node (identity is the mDNS MAC).

State and command handlers are wired here. Commands address entities by Native
API ``key``, stored on each capability's options at pair time. Light, media,
cover, and climate use bare capability IDs because Homey's system UIs only
bind those.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

from aioesphomeapi import (
    DeviceInfo,
    EntityCategory,
    EntityState,
)
from homey.device import Device
from homey.discovery_result import DiscoveryResult
from homey.discovery_result_mdns_sd import DiscoveryResultMDNSSD

from homey_esphomedriver.commands import DeviceEntityCommandHandler
from homey_esphomedriver.esphome_client import (
    DEFAULT_API_PORT,
    EspHomeClient,
    SessionState,
)
from homey_esphomedriver.esphome_driver import EspHomeDriver
from homey_esphomedriver.esphome_types import HomeyEspHomeDeviceOption
from homey_esphomedriver.esphome_util import (
    debug_log,
    device_info_settings,
    error_key,
    normalize_mac,
)
from homey_esphomedriver.mapping import (
    REFRESH_CAPABILITY,
    REFRESH_CAPABILITY_OPTIONS,
    DeviceEntityMapper,
)
from homey_esphomedriver.profile import BrandProfile
from homey_esphomedriver.refresh import plan_capability_refresh
from homey_esphomedriver.state import (
    DeviceEntityStateHandler,
)


class _EspHomeDeviceClient(EspHomeClient):
    """Runtime session that forwards lifecycle hooks to :class:`EspHomeDevice`."""

    def __init__(self, device: EspHomeDevice, *args: Any, **kwargs: Any) -> None:
        self._device = device
        super().__init__(*args, **kwargs)

    async def on_connected(self, device_info: DeviceInfo) -> None:
        await self._device._on_client_connected(device_info)

    async def on_disconnected(self, expected_disconnect: bool) -> None:
        task = asyncio.ensure_future(
            self._device._on_client_disconnected(expected_disconnect)
        )
        task.add_done_callback(self._device._on_state_task_done)

    async def on_connect_error(self, error: Exception) -> None:
        task = asyncio.ensure_future(self._device._on_client_connect_error(error))
        task.add_done_callback(self._device._on_state_task_done)


class EspHomeDevice(Device[EspHomeDriver]):
    """
    Homey device backed by one ESPHome node.

    Extend this class and export it from ``device.py`` as ``homey_export``.
    Override :meth:`on_esphome_init` / :meth:`on_esphome_uninit` instead of
    :meth:`on_init` / :meth:`on_uninit`.

    Example:
        ```python
        from homey_esphomedriver import EspHomeDevice

        homey_export = EspHomeDevice
        ```
    """

    _client: EspHomeClient | None
    _commands: DeviceEntityCommandHandler
    _state_handler: DeviceEntityStateHandler

    @property
    def brand_profile(self) -> BrandProfile:
        """Product profile from the owning driver."""
        return self.driver.brand_profile

    @property
    def client(self) -> EspHomeClient | None:
        """Live Native API session; ``None`` until a host is known and started."""
        return self._client

    async def on_init(self) -> None:
        """Wire capability listeners and start the Native API session.

        Do not override. Use :meth:`on_esphome_init` for brand setup.
        """
        await super().on_init()

        self._client = None

        device_class = self.get_setting("device_class")
        if device_class != "auto":
            await self._apply_device_class_setting(str(device_class))

        self._state_handler = DeviceEntityStateHandler(self)
        self._commands = DeviceEntityCommandHandler(self)
        await self._state_handler.init()
        await self._init_event_capability_defaults()
        await self._ensure_capabilities()
        for capability_id in self.get_capabilities():
            self._register_listener_for_capability(capability_id)

        await self._ensure_client_started()
        await self.on_esphome_init(self._client)

        self.log(f"Initialized EspHomeDevice {self.get_name()}")

    async def on_esphome_init(self, client: EspHomeClient | None) -> None:
        """Brand hook after capability wiring.

        Args:
            client: Live Native API session, or ``None`` when the node has no
                host yet (waiting on mDNS).
        """

    async def on_esphome_uninit(self) -> None:
        """Brand hook before the API session stops.

        Do not override :meth:`on_uninit`.
        """

    def debug(self, *args: object) -> None:
        """Write a debug log line when ``DEBUG`` is enabled in ``env.json``."""
        debug_log(self.log, *args)

    async def on_uninit(self) -> None:
        """Stop the API session and release state handlers.

        Do not override. Use :meth:`on_esphome_uninit` for brand cleanup.
        """
        await self.on_esphome_uninit()
        if self._client is not None:
            await self._client.stop()
            self._client = None
        self._state_handler.uninit()
        await super().on_uninit()

    async def on_discovery_result(self, discovery_result: DiscoveryResult) -> bool:
        """Match discovery results by MAC even when separator/casing differs."""
        return normalize_mac(discovery_result.id) == normalize_mac(
            str(self.get_data()["id"])
        )

    async def on_discovery_available(self, discovery_result: DiscoveryResult) -> None:
        """Refresh address from discovery and ensure the API session is running."""
        result = cast(DiscoveryResultMDNSSD, discovery_result)
        self.log(
            f"ESPHome device available at {result.address}:{result.port} "
            f"(host={result.host})"
        )
        await self._apply_discovery_endpoint(result)
        await self._ensure_client_started()
        await self._request_connect()

    async def on_discovery_address_changed(
        self, discovery_result: DiscoveryResult
    ) -> None:
        """Persist the new address when the node moves on the LAN."""
        result = cast(DiscoveryResultMDNSSD, discovery_result)
        await self._apply_discovery_endpoint(result)
        self.log(
            f"ESPHome device address changed to {result.address}:{result.port} "
            f"(host={result.host})"
        )

    async def on_discovery_last_seen_changed(
        self, discovery_result: DiscoveryResult
    ) -> None:
        """Connect immediately when Homey rediscovers the node, skipping backoff."""
        result = cast(DiscoveryResultMDNSSD, discovery_result)
        self.log(f"ESPHome device last seen updated ({result.address})")
        await self._request_connect()

    async def on_settings(
        self,
        old_settings: dict[str, bool | float | str | None],
        new_settings: dict[str, bool | float | str | None],
        changed_keys: tuple[str, ...],
    ) -> str | None:
        """Apply device-class override and diagnostic/configuration toggles."""
        del old_settings

        if "device_class" in changed_keys:
            await self._apply_device_class_setting(str(new_settings["device_class"]))
        if "show_diagnostics" in changed_keys:
            await self._apply_category_capabilities(
                bool(new_settings.get("show_diagnostics")),
                EntityCategory.DIAGNOSTIC,
                "diagnostic_capabilities",
            )
        if "show_configuration" in changed_keys:
            await self._apply_category_capabilities(
                bool(new_settings.get("show_configuration")),
                EntityCategory.CONFIG,
                "configuration_capabilities",
            )
        return None

    async def apply_connection(
        self,
        *,
        host: str,
        port: int,
        noise_psk: str | None,
    ) -> None:
        """Persist a repaired endpoint and restart the Native API session."""
        await self.set_store_value("address", host)
        await self.set_store_value("port", port)
        await self.set_store_value("noise_psk", noise_psk or "")
        await self.set_settings({"host": host, "port": str(port)})
        if self._client is not None:
            await self._client.stop()
            self._client = None
        await self._ensure_client_started()

    async def _apply_device_class_setting(self, value: str) -> None:
        """Set Homey class from the device_class setting (auto restores mapped)."""
        target = self.get_store()["auto_class"] if value == "auto" else value
        await self.set_class(target)

    async def _apply_category_capabilities(
        self,
        enabled: bool,
        category: EntityCategory,
        store_key: str,
    ) -> None:
        """Add or remove capabilities for one entity category from the live device."""
        if not enabled:
            # Batch — per-cap removeCapability reinitializes and times out
            # on entity-heavy nodes inside on_settings ACK.
            await self._remove_capabilities(list(self.get_store().get(store_key) or []))
            await self.set_store_value(store_key, [])
            await self._state_handler.init()
            return

        if self._client is None:
            raise ValueError(self.homey.translate("errors.device_not_connected"))

        entities, _services = await self._client.list_entities_services()
        existing = list(self.get_capabilities())
        scratch = self._mapping_device(existing)
        DeviceEntityMapper.map(
            entities, scratch, category_only=category, profile=self.brand_profile
        )
        added = [
            capability_id
            for capability_id in scratch["capabilities"]
            if capability_id not in existing
        ]
        await self._add_capabilities(
            added,
            {
                capability_id: scratch["capabilitiesOptions"][capability_id]
                for capability_id in added
            },
        )

        await self.set_store_value(store_key, added)
        await self._state_handler.init()

    async def _ensure_capabilities(self) -> None:
        """Add device-owned caps missing on devices paired before they existed."""
        missing = {
            capability_id: dict(capability_options)
            for capability_id, capability_options in (
                (REFRESH_CAPABILITY, REFRESH_CAPABILITY_OPTIONS),
            )
            if not self.has_capability(capability_id)
        }
        await self._add_capabilities(list(missing), missing)

    async def _refresh_capabilities(self, _value: Any = True, **_kwargs: Any) -> None:
        """Add/remove capabilities from a live remap; keep unchanged Homey ids."""
        client = self._require_client()
        entities, _services = await client.list_entities_services()
        scratch = self._mapping_device([])
        DeviceEntityMapper.map_device(
            entities,
            scratch,
            profile=self.brand_profile,
            diagnostics=self.get_setting("show_diagnostics"),
            configuration=self.get_setting("show_configuration"),
        )

        to_remove, to_add, to_update = plan_capability_refresh(
            self._capabilities_options, scratch["capabilitiesOptions"]
        )
        await self._remove_capabilities(to_remove)
        await self._add_capabilities(
            [capability_id for capability_id, _options in to_add],
            dict(to_add),
        )
        for capability_id, options in to_update:
            await self.set_capability_options(capability_id, options)

        mapped_class = scratch.get("class")
        if mapped_class and self.get_setting("device_class") == "auto":
            await self.set_store_value("auto_class", mapped_class)
            if self.get_class() != mapped_class:
                await self.set_class(mapped_class)

        await self.set_store_value(
            "diagnostic_capabilities",
            self._capabilities_for_entity_keys(
                {
                    entity.key
                    for entity in entities
                    if entity.entity_category == EntityCategory.DIAGNOSTIC
                }
            ),
        )
        await self.set_store_value(
            "configuration_capabilities",
            self._capabilities_for_entity_keys(
                {
                    entity.key
                    for entity in entities
                    if entity.entity_category == EntityCategory.CONFIG
                }
            ),
        )

        await self._state_handler.init()

    def _mapping_device(self, capabilities: list[str]) -> HomeyEspHomeDeviceOption:
        """Pair-time payload for a live remap."""
        return {
            "name": self.get_name(),
            "data": dict(self.get_data()),
            "store": {},
            "settings": {},
            "capabilities": list(capabilities),
            "capabilitiesOptions": {},
        }

    async def _add_capabilities(
        self,
        capability_ids: list[str],
        options: dict[str, dict[str, Any]],
    ) -> None:
        """Batch-add capabilities and register listeners for the new ids."""
        if not capability_ids:
            return
        await self._client_emit(
            "addCapabilities",
            data={"capabilityIds": capability_ids, "capabilitiesOptions": options},
        )
        self._capabilities = [*self._capabilities, *capability_ids]
        self._capabilities_options.update(options)
        for capability_id in capability_ids:
            self._register_listener_for_capability(capability_id)

    async def _remove_capabilities(self, capability_ids: list[str]) -> None:
        """Batch-remove capabilities and drop their local state."""
        if not capability_ids:
            return
        await self._client_emit(
            "removeCapabilities",
            data={"capabilityIds": capability_ids},
        )
        removed = set(capability_ids)
        self._capabilities = [
            capability_id
            for capability_id in self._capabilities
            if capability_id not in removed
        ]
        for capability_id in capability_ids:
            del self._capabilities_options[capability_id]
            self._state.pop(capability_id, None)

    def _capabilities_for_entity_keys(self, keys: set[int]) -> list[str]:
        """Capability ids whose pair-time ``key`` is in ``keys``."""
        return [
            capability_id
            for capability_id, options in self._capabilities_options.items()
            if (key := options.get("key")) is not None and int(key) in keys
        ]

    def _register_listener_for_capability(self, capability_id: str) -> None:
        """Register a settable-capability listener (pair-time and category toggles)."""
        if capability_id == REFRESH_CAPABILITY:
            self.register_capability_listener(
                REFRESH_CAPABILITY, self._refresh_capabilities
            )
            return
        self._commands.register_listener_for_capability(capability_id)

    async def is_on_run_listener(self, capability_id: str) -> Any:
        """Return the current value of a boolean capability for Flow conditions."""
        return self.get_capability_value(capability_id)

    async def is_value_run_listener(self, value: Any, capability_id: str) -> bool:
        """Return whether ``value`` matches the current capability value."""
        if not value:
            return False
        return value == self.get_capability_value(capability_id)

    async def _init_event_capability_defaults(self) -> None:
        """Seed event caps with Idle / not-ringing so they are not null at start."""
        for capability_id in self.get_capabilities():
            if self.get_capability_value(capability_id) is not None:
                continue
            if capability_id.startswith("alarm_doorbell."):
                await self.set_capability_value(capability_id, False)
            elif capability_id.startswith(("event_button.", "event_generic.")):
                await self.set_capability_value(capability_id, "idle")

    async def _ensure_client_started(self) -> None:
        """Create and start the long-lived API session from device settings."""
        if self._client is not None:
            return

        host = str(
            self.get_setting("host") or self.get_store().get("address") or ""
        ).strip()
        if not host:
            self.error("ESPHome host is missing; waiting for discovery or settings")
            return

        port = int(
            self.get_setting("port") or self.get_store().get("port") or DEFAULT_API_PORT
        )
        noise_psk = str(self.get_store().get("noise_psk") or "").strip() or None
        expected_mac = str(self.get_data()["id"])

        name = str(self.get_setting("hostname") or "").strip() or None
        self._client = _EspHomeDeviceClient(
            self,
            host,
            port,
            name=name,
            noise_psk=noise_psk,
            expected_mac=expected_mac,
            client_info=self.brand_profile.client_info,
            deep_sleep=self.get_setting("deep_sleep") == "Yes",
        )
        await self._client.start(self._on_entity_state)

    async def _request_connect(self) -> None:
        """Ask ReconnectLogic to try immediately when Homey discovery sees the node."""
        if self._client is not None:
            await self._client.request_connect()

    async def _apply_discovery_endpoint(self, result: DiscoveryResultMDNSSD) -> None:
        """Persist discovery address into store/settings and live client config."""
        await self.set_store_value("address", result.address)
        if result.host is not None:
            await self.set_store_value("host", result.host)
        if result.port is not None:
            await self.set_store_value("port", result.port)

        settings_update: dict[str, str] = {"host": result.address}
        if result.port is not None:
            settings_update["port"] = str(result.port)
        await self.set_settings(settings_update)

        if self._client is not None:
            port = int(result.port or self._client.port)
            if result.address != self._client.host or port != self._client.port:
                await self._client.update_endpoint(host=result.address, port=port)

    def _on_entity_state(self, state: EntityState) -> None:
        """Bridge sync aioesphomeapi callbacks onto the Homey event loop."""
        task = asyncio.ensure_future(self._state_handler.handle_state(state))
        task.add_done_callback(self._on_state_task_done)

    async def _on_client_connected(self, device_info: DeviceInfo) -> None:
        await self._sync_device_information(device_info)
        await self.set_available()
        if self._client is not None:
            self._client.mark_ready()

        native_app_suggestion = self.brand_profile.native_app_suggestion(
            device_info.project_name
        )
        if native_app_suggestion:
            message = self.homey.translate(
                "nativeAppSuggestion",
                appName=native_app_suggestion,
            )
            self.homey.set_timeout(
                lambda: asyncio.ensure_future(
                    self.set_warning(message)
                ).add_done_callback(self._on_state_task_done),
                1000,
            )

    async def _sync_device_information(self, device_info: DeviceInfo) -> None:
        """Mirror DeviceInfo into the read-only Device Information settings."""
        host = str(self.get_setting("host") or self.get_store().get("address") or "")
        has_encryption = bool(str(self.get_store().get("noise_psk") or "").strip())
        await self.set_settings(
            device_info_settings(
                device_info,
                host=host,
                encrypted=has_encryption,
            )
        )

    def _keep_available_while_offline(self) -> bool:
        """Keep Homey available while the session is up or the node deep-sleeps."""
        if self._client is not None and self._client.state in (
            SessionState.CONNECTED,
            SessionState.READY,
        ):
            return True
        info = self._client.device_info if self._client is not None else None
        return info is not None and info.has_deep_sleep

    async def _on_client_disconnected(self, _expected: bool) -> None:
        if self._keep_available_while_offline():
            return
        await self.set_unavailable(self.homey.translate("errors.connection_lost"))

    async def _on_client_connect_error(self, error: Exception) -> None:
        self.error("ESPHome connect error", error)
        if self._keep_available_while_offline():
            return
        await self.set_unavailable(self.homey.translate(error_key(error)))

    def _on_state_task_done(self, task: asyncio.Future[Any]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            self.error(error)

    def _require_client(self) -> EspHomeClient:
        """Return the live session, or raise if the node is not ready."""
        if self._client is None or self._client.state is not SessionState.READY:
            raise RuntimeError(self.homey.translate("errors.device_not_connected"))
        return self._client
