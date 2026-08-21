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
)
from homey.device import Device
from homey.discovery_result import DiscoveryResult
from homey.discovery_result_mdns_sd import DiscoveryResultMDNSSD

from homey_esphomedriver.capabilities import DeviceCapabilityHandler
from homey_esphomedriver.entities.commands import DeviceEntityCommandHandler
from homey_esphomedriver.entities.mapping import REFRESH_CAPABILITY
from homey_esphomedriver.entities.state import (
    DeviceEntityStateHandler,
)
from homey_esphomedriver.esphome_client import (
    DEFAULT_API_PORT,
    EspHomeClient,
)
from homey_esphomedriver.esphome_driver import EspHomeDriver
from homey_esphomedriver.esphome_util import (
    device_info_settings,
    error_key,
    normalize_mac,
)
from homey_esphomedriver.profile import BrandProfile


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
    _capability_handler: DeviceCapabilityHandler
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
        self._capability_handler = DeviceCapabilityHandler(self)
        await self._state_handler.init()
        await self._init_event_capability_defaults()
        await self._capability_handler.ensure()
        self.register_capability_listener(
            REFRESH_CAPABILITY, self._capability_handler.refresh
        )
        self._commands.register_listeners()

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
        if self._client is not None:
            await self._client.request_connect()

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
        if self._client is not None:
            await self._client.request_connect()

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
            await self._capability_handler.apply_category(
                bool(new_settings.get("show_diagnostics")),
                EntityCategory.DIAGNOSTIC,
                "diagnostic_capabilities",
            )
        if "show_configuration" in changed_keys:
            await self._capability_handler.apply_category(
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

    def _register_listener_for_capability(self, capability_id: str) -> None:
        """Register a settable-capability listener (pair-time and category toggles)."""
        if capability_id == REFRESH_CAPABILITY:
            self.register_capability_listener(
                REFRESH_CAPABILITY, self._capability_handler.refresh
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
        self._client = EspHomeClient(
            host,
            port,
            name=name,
            noise_psk=noise_psk,
            expected_mac=expected_mac,
            client_info=self.brand_profile.client_info,
            deep_sleep=self.get_setting("deep_sleep") == "Yes",
            on_connected=self._on_client_connected,
            on_disconnected=self._on_client_disconnected,
            on_connect_error=self._on_client_connect_error,
        )
        await self._client.start(self._state_handler.handle_state)

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

    async def _on_client_connected(self, device_info: DeviceInfo) -> None:
        await self._sync_device_information(device_info)
        await self.set_available()

        native_app_suggestion = self.brand_profile.native_app_suggestion(
            device_info.project_name
        )
        if native_app_suggestion:
            message = self.homey.translate(
                "nativeAppSuggestion",
                appName=native_app_suggestion,
            )

            async def show_warning() -> None:
                try:
                    await self.set_warning(message)
                except Exception as error:
                    self.error(error)

            self.homey.set_timeout(
                lambda: asyncio.ensure_future(show_warning()),
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

    async def _on_client_disconnected(self, expected: bool) -> None:
        info = self._client.device_info if self._client is not None else None
        if expected or (info is not None and info.has_deep_sleep):
            return
        await self.set_unavailable(self.homey.translate("errors.connection_lost"))

    async def _on_client_connect_error(self, error: Exception) -> None:
        self.error("ESPHome connect error", error)
        info = self._client.device_info if self._client is not None else None
        if info is not None and info.has_deep_sleep:
            return
        await self.set_unavailable(self.homey.translate(error_key(error)))

    def _require_client(self) -> EspHomeClient:
        """Return the live session, or raise if the node is not ready."""
        if self._client is None or not self._client.available:
            raise RuntimeError(self.homey.translate("errors.device_not_connected"))
        return self._client
