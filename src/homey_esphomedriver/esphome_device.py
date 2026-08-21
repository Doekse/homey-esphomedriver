"""Homey Device for one ESPHome node (identity is the mDNS MAC).

Owns :class:`~homey_esphomedriver.esphome_client.EspHomeClient` and the
capability / command / state handlers. Homey discovery and settings drive
persist + reconnect; entity I/O lives on the handlers.
"""

from __future__ import annotations

import asyncio
from typing import cast

from aioesphomeapi import (
    DeviceInfo,
    EntityCategory,
)
from homey.device import Device
from homey.discovery_result import DiscoveryResult
from homey.discovery_result_mdns_sd import DiscoveryResultMDNSSD

from homey_esphomedriver.capabilities import DeviceCapabilityHandler
from homey_esphomedriver.entities.commands import DeviceEntityCommandHandler
from homey_esphomedriver.entities.state import DeviceEntityStateHandler
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
        """Wire handlers and start the Native API session.

        Do not override. Use :meth:`on_esphome_init` for brand setup.
        """
        await super().on_init()

        self._client = None
        self._state_handler = DeviceEntityStateHandler(self)
        self._commands = DeviceEntityCommandHandler(self)
        self._capability_handler = DeviceCapabilityHandler(self)

        device_class = self.get_setting("device_class")
        if device_class != "auto":
            await self._apply_device_class_setting(str(device_class))

        await self._state_handler.init()
        await self._capability_handler.ensure()

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
        client = self._client
        await self._apply_discovery_endpoint(result)
        await self._ensure_client_started()
        if client is not None:
            await client.request_connect()

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
        self.log(f"ESPHome device last seen updated ({discovery_result.address})")
        client = self._client
        if client is not None:
            await client.request_connect()

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
        await self._persist_endpoint(host, port, noise_psk=noise_psk or "")
        if self._client is not None:
            await self._client.stop()
            self._client = None
        await self._ensure_client_started()

    async def _apply_device_class_setting(self, value: str) -> None:
        """Set Homey class from the device_class setting (auto restores mapped)."""
        target = self.get_store()["auto_class"] if value == "auto" else value
        await self.set_class(target)

    async def _ensure_client_started(self) -> None:
        """Create and start the long-lived API session from device settings."""
        if self._client is not None:
            return

        store = self.get_store()
        host = str(self.get_setting("host") or store.get("address") or "").strip()
        if not host:
            self.error("ESPHome host is missing; waiting for discovery or settings")
            return

        port = int(self.get_setting("port") or store.get("port") or DEFAULT_API_PORT)
        noise_psk = str(store.get("noise_psk") or "").strip() or None
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
            on_connected=self._on_connected,
            on_disconnected=self._on_disconnected,
            on_connect_error=self._on_connect_error,
        )
        await self._client.start(self._state_handler.handle_state)

    async def _persist_endpoint(
        self,
        host: str,
        port: int,
        *,
        hostname: str | None = None,
        noise_psk: str | None = None,
    ) -> None:
        """Write endpoint into store and settings (shared by discovery and repair)."""
        await self.set_store_value("address", host)
        await self.set_store_value("port", port)
        if hostname is not None:
            await self.set_store_value("host", hostname)
        if noise_psk is not None:
            await self.set_store_value("noise_psk", noise_psk)
        await self.set_settings({"host": host, "port": str(port)})

    async def _apply_discovery_endpoint(self, result: DiscoveryResultMDNSSD) -> None:
        """Persist discovery address and update the live client when it changed."""
        host = result.address
        if not host:
            return
        port = result.port or DEFAULT_API_PORT
        await self._persist_endpoint(host, port, hostname=result.host)
        client = self._client
        if client is not None and (host != client.host or port != client.port):
            await client.update_endpoint(host=host, port=port)

    async def _on_connected(self, device_info: DeviceInfo) -> None:
        client = cast(EspHomeClient, self._client)
        has_encryption = bool(str(self.get_store().get("noise_psk") or "").strip())
        await self.set_settings(
            device_info_settings(
                device_info,
                host=client.host,
                encrypted=has_encryption,
            )
        )
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

    async def _on_disconnected(self, expected: bool) -> None:
        if expected:
            return
        client = self._client
        if client is not None and client.deep_sleep:
            return
        await self.set_unavailable(self.homey.translate("errors.connection_lost"))

    async def _on_connect_error(self, error: Exception) -> None:
        self.error("ESPHome connect error", error)
        client = self._client
        if client is not None and client.deep_sleep:
            return
        await self.set_unavailable(self.homey.translate(error_key(error)))

    def _require_client(self) -> EspHomeClient:
        """Return the live session, or raise if the node is not ready."""
        client = self._client
        if client is None or not client.available:
            raise RuntimeError(self.homey.translate("errors.device_not_connected"))
        return client
