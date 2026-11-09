"""Homey Device for one ESPHome node (identity is the mDNS MAC).

Owns :class:`~homey_esphomedriver.esphome_client.EspHomeClient` and the
capability bindings. Homey discovery and settings drive persist + reconnect;
entity I/O lives on :class:`~homey_esphomedriver.bindings.CapabilityBindings`.
"""

from __future__ import annotations

import asyncio
from typing import cast

from aioesphomeapi import DeviceInfo, EntityState
from homey.device import Device
from homey.discovery_result import DiscoveryResult
from homey.discovery_result_mdns_sd import DiscoveryResultMDNSSD

from homey_esphomedriver.bindings import CapabilityBindings, StateListener
from homey_esphomedriver.esphome_client import (
    DEFAULT_API_PORT,
    EspHomeClient,
)
from homey_esphomedriver.esphome_driver import EspHomeDriver
from homey_esphomedriver.esphome_util import (
    changed_values,
    device_info_settings,
    error_key,
    normalize_mac,
)
from homey_esphomedriver.profile import BrandProfile
from homey_esphomedriver.settings import SettingEntitySync
from homey_esphomedriver.system import BoundEntity, ReportParser, SetParser


class EspHomeDevice(Device[EspHomeDriver]):
    """
    Homey device backed by one ESPHome node.

    Extend this class and export it from ``device.py`` as ``homey_export``.
    Override :meth:`on_esphome_init` / :meth:`on_esphome_connected` /
    :meth:`on_esphome_uninit` instead of :meth:`on_init` / :meth:`on_uninit`,
    and bind the driver's capabilities to entities in :meth:`on_esphome_init`.

    Example:
        ```python
        from homey_esphomedriver import EspHomeDevice


        class Air1Device(EspHomeDevice):
            async def on_esphome_init(self, client):
                self.register_capability("measure_co2", "sensor", "CO2")


        homey_export = Air1Device
        ```
    """

    _client: EspHomeClient | None
    _mac: str
    _bindings: CapabilityBindings
    _setting_sync: SettingEntitySync

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
        # Device data never changes, and Homey only matches discovery after on_init.
        self._mac = normalize_mac(str(self.get_data()["id"]))
        self._bindings = CapabilityBindings(self)
        self._setting_sync = SettingEntitySync(self)

        # Started only after the brand hook, so the capabilities registered
        # there apply to the connect dump.
        client = self._create_client()
        await self.on_esphome_init(client)
        if client is not None:
            await client.start(self._on_state)

        self.log(f"Initialized EspHomeDevice {self.get_name()}")

    async def on_esphome_init(self, client: EspHomeClient | None) -> None:
        """Brand hook to bind capabilities before the session starts.

        Call :meth:`register_capability` and :meth:`register_state_listener`
        here.

        Args:
            client: Native API session, started once this hook returns, or
                ``None`` when the node has no host yet (waiting on mDNS).
        """

    async def on_esphome_connected(self, client: EspHomeClient) -> None:
        """Brand hook after each Native API login, including reconnects.

        Homey already shows the device as available here, but the session
        is not READY until this hook returns. Do not issue commands until
        ``client.available`` or :meth:`_require_client`.
        """

    async def on_esphome_uninit(self) -> None:
        """Brand hook before the API session stops.

        Do not override :meth:`on_uninit`.
        """

    def register_capability(
        self,
        capability_id: str,
        domain: str,
        name: str,
        *,
        device_id: int = 0,
        set_parser: SetParser | None = None,
        report_parser: ReportParser | None = None,
    ) -> None:
        """Bind a capability of this device to an ESPHome entity.

        The capability must already be on the device; the driver declares it.
        The system capabilities supply parsers for Homey's own capabilities;
        pass a parser to override them, or for an app's own capability. Call
        from :meth:`on_esphome_init` so the connect dump reaches it; a later
        call binds right away and replays the entity's last state.

        Example:
            ```python
            async def on_esphome_init(self, client):
                self.register_capability("measure_co2", "sensor", "CO2")
                self.register_capability("dim.led", "light", "Status LED")
                self.register_capability(
                    "air_quality", "sensor", "VOC Index",
                    report_parser=lambda state, entity: state.state > 150,
                )
            ```

        Args:
            capability_id: Capability on this device, such as ``dim.led``.
            domain: ESPHome entity domain, such as ``light`` or ``sensor``.
            name: Entity name the YAML author chose.
            device_id: Sub-device the entity belongs to; 0 is the node itself.
            set_parser: ``(value, opts, entity)`` to keyword arguments for
                ``<domain>_command``, or ``None`` to send nothing.
            report_parser: ``(state, entity)`` to the capability value, or
                ``None`` to leave it as is.

        Raises:
            ValueError: The device lacks the capability, the domain is
                unknown, or no parser is available.
        """
        self._bindings.register_capability(
            capability_id,
            domain,
            name,
            device_id=device_id,
            set_parser=set_parser,
            report_parser=report_parser,
        )

    def unregister_capability(self, capability_id: str) -> None:
        """Stop reporting and setting a capability; the capability stays."""
        self._bindings.unregister_capability(capability_id)

    def register_state_listener(
        self,
        domain: str,
        name: str,
        listener: StateListener,
        *,
        device_id: int = 0,
    ) -> None:
        """Call ``listener(state, entity)`` with every state of an entity.

        For what no capability shows, such as firing an app's own Flow card
        on an event. Runs inline in the Native API read callback, so a
        coroutine it returns runs as a task.
        """
        self._bindings.register_state_listener(
            domain, name, listener, device_id=device_id
        )

    def entity(self, domain: str, name: str, device_id: int = 0) -> BoundEntity | None:
        """An entity of the current connection, to send it a command yourself.

        Example:
            ```python
            entity = self.entity("button", "Calibrate")
            if entity is not None:
                self.client.command("button_command", entity.key)
            ```
        """
        return self._bindings.entity(domain, name, device_id)

    async def on_uninit(self) -> None:
        """Stop the API session and release state handlers.

        Do not override. Use :meth:`on_esphome_uninit` for brand cleanup.
        """
        await self.on_esphome_uninit()
        if self._client is not None:
            await self._client.stop()
            self._client = None
        self._setting_sync.uninit()
        self._bindings.unbind()
        await super().on_uninit()

    async def on_discovery_result(self, discovery_result: DiscoveryResult) -> bool:
        """Match discovery results by MAC even when separator/casing differs."""
        return normalize_mac(discovery_result.id) == self._mac

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
        """Write settings linked to an entity to the node.

        An invalid value, or a node that is offline and not a deep-sleep node,
        rejects the save. A subclass that handles settings of its own calls
        this first, so a rejected save applies nothing.
        """
        del old_settings
        return await self._setting_sync.on_settings(new_settings, changed_keys)

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

    async def _ensure_client_started(self) -> None:
        """Create and start the long-lived API session from device settings."""
        if self._client is not None:
            return
        client = self._create_client()
        if client is not None:
            await client.start(self._on_state)

    def _create_client(self) -> EspHomeClient | None:
        """Create the API session from device settings without starting it."""
        if self._client is not None:
            return self._client

        store = self.get_store()
        host = str(self.get_setting("host") or store.get("address") or "").strip()
        if not host:
            self.error("ESPHome host is missing; waiting for discovery or settings")
            return None

        port = int(self.get_setting("port") or store.get("port") or DEFAULT_API_PORT)
        noise_psk = str(store.get("noise_psk") or "").strip() or None

        name = str(self.get_setting("hostname") or "").strip() or None
        self._client = EspHomeClient(
            host,
            port,
            name=name,
            noise_psk=noise_psk,
            expected_mac=self._mac,
            client_info=self.brand_profile.client_info,
            deep_sleep=self.get_setting("deep_sleep") == "Yes",
            on_entities=self._bindings.bind,
            on_connected=self._on_connected,
            on_disconnected=self._on_disconnected,
            on_connect_error=self._on_connect_error,
            on_ready=self._on_ready,
        )
        return self._client

    async def _persist_endpoint(
        self,
        host: str,
        port: int,
        *,
        hostname: str | None = None,
        noise_psk: str | None = None,
    ) -> None:
        """Write endpoint into store and settings (shared by discovery and repair).

        Only changed values are written; discovery repeats the same endpoint.
        """
        store = changed_values(
            self.get_store(),
            {"address": host, "port": port, "host": hostname, "noise_psk": noise_psk},
        )
        for key, value in store.items():
            if value is not None:
                await self.set_store_value(key, value)
        settings = changed_values(
            self.get_settings(), {"host": host, "port": str(port)}
        )
        if settings:
            await self.set_settings(settings)

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
        accepted = self.brand_profile.accepts_project(device_info.project_name)
        has_encryption = bool(str(self.get_store().get("noise_psk") or "").strip())
        settings = changed_values(
            self.get_settings(),
            device_info_settings(
                device_info,
                host=client.host,
                encrypted=has_encryption,
            ),
        )
        if settings:
            await self.set_settings(settings)
        await self.set_available()
        self._schedule_project_warning(device_info, accepted=accepted)
        await self.on_esphome_connected(client)

    def _on_state(self, state: EntityState) -> None:
        """Mirror settings linked to an entity, then update capabilities."""
        self._setting_sync.on_state(state)
        self._bindings.handle_state(state)

    async def _on_ready(self) -> None:
        """The session accepts commands: send settings saved while asleep."""
        await self._setting_sync.flush_pending()

    def _schedule_project_warning(
        self, device_info: DeviceInfo, *, accepted: bool
    ) -> None:
        """Warn when this app should not drive the node.

        A native-app suggestion wins when the project is also rejected.
        """
        project_name = device_info.project_name
        native_app = self.brand_profile.native_app_suggestion(project_name)
        if native_app:
            message = self.homey.translate("nativeAppSuggestion", appName=native_app)
        elif not accepted:
            message = self.homey.translate(
                "warnings.project_mismatch", project=project_name
            )
        else:
            return
        self._schedule_warning(message)

    def _schedule_warning(self, message: str | None) -> None:
        if not message:
            return

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
        """A clean sleep goodbye keeps the last state; a drop does not."""
        if expected:
            return
        await self.set_unavailable(self.homey.translate("errors.connection_lost"))

    async def _on_connect_error(self, error: Exception) -> None:
        """A dial that never logs in is unavailable, including deep sleep."""
        self.error(f"ESPHome connect error: {error}")
        await self.set_unavailable(self.homey.translate(error_key(error)))

    def _require_client(self) -> EspHomeClient:
        """Return the live session, or raise if the node is not ready."""
        client = self._client
        if client is None or not client.available:
            raise RuntimeError(self.homey.translate("errors.device_not_connected"))
        return client
