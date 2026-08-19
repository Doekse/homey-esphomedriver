"""Runtime Homey device backed by one ESPHome node (identity is the mDNS MAC).

State handlers and capability listeners are wired here. Commands address
entities by Native API ``key``, stored on each capability's options at pair time.
Light, media, cover, and climate use bare capability IDs because Homey's
system UIs only bind those.
"""

from __future__ import annotations

import asyncio
import colorsys
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast

from aioesphomeapi import (
    AlarmControlPanelCommand,
    ClimateFanMode,
    ClimateMode,
    ClimatePreset,
    ClimateSwingMode,
    ColorMode,
    DeviceInfo,
    EntityCategory,
    EntityState,
    LockCommand,
    MediaPlayerCommand,
    WaterHeaterMode,
)
from homey.device import Device
from homey.discovery_result import DiscoveryResult
from homey.discovery_result_mdns_sd import DiscoveryResultMDNSSD

from homey_esphomedriver.esphome_client import DEFAULT_API_PORT, EspHomeClient
from homey_esphomedriver.esphome_driver import EspHomeDriver
from homey_esphomedriver.esphome_types import HomeyEspHomeDeviceOption
from homey_esphomedriver.esphome_util import (
    debug_log,
    device_info_settings,
    error_key,
    normalize_mac,
)
from homey_esphomedriver.mapping import (
    DeviceEntityMapper,
)
from homey_esphomedriver.profile import BrandProfile
from homey_esphomedriver.state import (
    DeviceEntityStateHandler,
)
from homey_esphomedriver.units import (
    convert_temperature_from_celsius,
    kelvin_to_mireds,
)

CapabilityListener = Callable[..., Awaitable[None]]


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
        self._expected_disconnect = False

        device_class = self.get_setting("device_class")
        if device_class != "auto":
            await self._apply_device_class_setting(str(device_class))

        self._state_handler = DeviceEntityStateHandler(self)
        self._state_handler.init()
        await self._init_event_capability_defaults()

        self._register_capability_listener_if_available(
            "onoff",
            self._on_capability_onoff,
        )
        for capability_id in self._get_on_off_capabilities():
            self.register_capability_listener(
                capability_id,
                self._listener_with_capability_id(
                    self._on_capability_onoff,
                    capability_id,
                ),
            )
        for capability_id in self._get_button_capabilities():
            self.register_capability_listener(
                capability_id,
                self._listener_with_capability_id(
                    self._on_capability_button,
                    capability_id,
                    pass_value=False,
                ),
            )
        for capability_id in self._get_number_capabilities():
            self.register_capability_listener(
                capability_id,
                self._listener_with_capability_id(
                    self._on_capability_number,
                    capability_id,
                ),
            )
        for capability_id in self._get_select_capabilities():
            self.register_capability_listener(
                capability_id,
                self._listener_with_capability_id(
                    self._on_capability_select,
                    capability_id,
                ),
            )

        self._register_capability_listener_if_available(
            "windowcoverings_state",
            self._on_capability_windowcoverings_state,
        )
        self._register_capability_listener_if_available(
            "windowcoverings_set",
            self._on_capability_windowcoverings_set,
        )
        self._register_capability_listener_if_available(
            "windowcoverings_tilt_set",
            self._on_capability_windowcoverings_tilt_set,
        )
        self._register_capability_listener_if_available(
            "windowcoverings_tilt_up",
            self._on_capability_windowcoverings_tilt_up,
        )
        self._register_capability_listener_if_available(
            "windowcoverings_tilt_down",
            self._on_capability_windowcoverings_tilt_down,
        )
        self._register_capability_listener_if_available(
            "garagedoor_closed",
            self._on_capability_garagedoor_closed,
        )
        self._register_capability_listener_if_available(
            "thermostat_mode",
            self._on_capability_thermostat_mode,
        )
        self._register_capability_listener_if_available(
            "thermostat_preset",
            self._on_capability_thermostat_preset,
        )
        self._register_capability_listener_if_available(
            "target_temperature",
            self._on_capability_target_temperature,
        )
        self._register_capability_listener_if_available(
            "target_temperature_min",
            self._on_capability_target_temperature_min,
        )
        self._register_capability_listener_if_available(
            "target_temperature_max",
            self._on_capability_target_temperature_max,
        )
        self._register_capability_listener_if_available(
            "target_humidity",
            self._on_capability_target_humidity,
        )
        self._register_capability_listener_if_available(
            "swing_mode",
            self._on_capability_swing_mode,
        )
        self._register_capability_listener_if_available(
            "homealarm_state",
            self._on_capability_homealarm_state,
        )
        self._register_capability_listener_if_available(
            "heater_operation_mode",
            self._on_capability_heater_operation_mode,
        )
        self._register_capability_listener_if_available(
            "fan_speed",
            self._on_capability_fan_speed,
        )
        self._register_capability_listener_if_available(
            "fan_oscillate",
            self._on_capability_fan_oscillate,
        )
        self._register_capability_listener_if_available(
            "fan_mode",
            self._on_capability_fan_mode,
        )
        self._register_capability_listener_if_available(
            "aircleaner_mode",
            self._on_capability_aircleaner_mode,
        )
        self._register_capability_listener_if_available(
            "speaker_playing",
            self._on_capability_speaker_playing,
        )
        self._register_capability_listener_if_available(
            "speaker_stop",
            self._on_capability_speaker_stop,
        )
        self._register_capability_listener_if_available(
            "volume_set",
            self._on_capability_volume_set,
        )
        self._register_capability_listener_if_available(
            "volume_mute",
            self._on_capability_volume_mute,
        )
        self._register_capability_listener_if_available(
            "volume_up",
            self._on_capability_volume_up,
        )
        self._register_capability_listener_if_available(
            "volume_down",
            self._on_capability_volume_down,
        )
        # Binary-sensor ``locked`` is status-only; lock entities are settable.
        if self.has_capability("locked") and self._get_entity_type("locked") == "lock":
            self.register_capability_listener("locked", self._on_capability_locked)
        self._register_capability_listener_if_available(
            "valve_position",
            self._on_capability_valve_position,
        )

        self._register_capability_listener_if_available("dim", self._on_capability_dim)
        if self.has_capability("light_hue") and self.has_capability("light_saturation"):
            self.register_multiple_capability_listener(
                ["light_hue", "light_saturation"],
                self._on_capability_light_hue_saturation,
            )
        self._register_capability_listener_if_available(
            "light_temperature",
            self._on_capability_light_temperature,
        )
        self._register_capability_listener_if_available(
            "light_mode",
            self._on_capability_light_mode,
        )
        self._register_capability_listener_if_available(
            "light_effect",
            self._on_capability_light_effect,
        )

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
            removed = list(self.get_store().get(store_key) or [])
            if removed:
                # Batch — per-cap removeCapability reinitializes and times out
                # on entity-heavy nodes inside on_settings ACK.
                await self._client_emit(
                    "removeCapabilities",
                    data={"capabilityIds": removed},
                )
                removed_set = set(removed)
                self._capabilities = [
                    capability_id
                    for capability_id in self._capabilities
                    if capability_id not in removed_set
                ]
                for capability_id in removed:
                    self._capabilities_options.pop(capability_id, None)
                    self._state.pop(capability_id, None)
            await self.set_store_value(store_key, [])
            self._state_handler.init()
            return

        if self._client is None:
            raise ValueError(self.homey.translate("errors.device_not_connected"))

        entities, _services = await self._client.list_entities_services()
        existing = list(self.get_capabilities())
        scratch: HomeyEspHomeDeviceOption = {
            "name": self.get_name(),
            "data": dict(self.get_data()),
            "store": {},
            "settings": {},
            "capabilities": list(existing),
            "capabilitiesOptions": {},
        }
        before = set(existing)
        DeviceEntityMapper.map(
            entities, scratch, category_only=category, profile=self.brand_profile
        )
        added = [
            capability_id
            for capability_id in scratch["capabilities"]
            if capability_id not in before
        ]

        if added:
            options = {
                capability_id: scratch["capabilitiesOptions"][capability_id]
                for capability_id in added
            }
            await self._client_emit(
                "addCapabilities",
                data={"capabilityIds": added, "capabilitiesOptions": options},
            )
            self._capabilities = [*self._capabilities, *added]
            self._capabilities_options.update(options)
            for capability_id in added:
                self._register_listener_for_capability(capability_id)

        await self.set_store_value(store_key, added)
        self._state_handler.init()
        # These capabilities were not present for the connect-time state dump.
        self._client.request_states()

    def _register_listener_for_capability(self, capability_id: str) -> None:
        """Register a settable-capability listener (pair-time and category toggles)."""
        if capability_id == "onoff" or capability_id.startswith("onoff."):
            self.register_capability_listener(
                capability_id,
                self._listener_with_capability_id(
                    self._on_capability_onoff,
                    capability_id,
                ),
            )
        elif capability_id.startswith(("button.", "restart", "identify")):
            self.register_capability_listener(
                capability_id,
                self._listener_with_capability_id(
                    self._on_capability_button,
                    capability_id,
                    pass_value=False,
                ),
            )
        elif capability_id.startswith(
            "esphome_number."
        ) and self.get_capability_options(capability_id).get("setable", False):
            self.register_capability_listener(
                capability_id,
                self._listener_with_capability_id(
                    self._on_capability_number,
                    capability_id,
                ),
            )
        elif capability_id.startswith("esphome_select."):
            self.register_capability_listener(
                capability_id,
                self._listener_with_capability_id(
                    self._on_capability_select,
                    capability_id,
                ),
            )
        elif capability_id == "swing_mode":
            self.register_capability_listener(
                capability_id,
                self._on_capability_swing_mode,
            )

    def _register_capability_listener_if_available(
        self,
        capability_id: str,
        listener: CapabilityListener,
    ) -> None:
        if not self.has_capability(capability_id):
            return
        self.register_capability_listener(capability_id, listener)

    async def is_on_run_listener(self, capability_id: str) -> Any:
        """Return the current value of a boolean capability for Flow conditions."""
        return self.get_capability_value(capability_id)

    async def is_value_run_listener(self, value: Any, capability_id: str) -> bool:
        """Return whether ``value`` matches the current capability value."""
        if not value:
            return False
        return value == self.get_capability_value(capability_id)

    def _get_entity_key(self, capability_id: str) -> int:
        """Return the ESPHome entity key stored on the capability at pair time."""
        return int(self.get_capability_options(capability_id)["key"])

    def _get_entity_type(self, capability_id: str) -> str | None:
        """Return the pair-time entity domain, or ``None`` if unset."""
        entity_type = self.get_capability_options(capability_id).get("entity_type")
        return str(entity_type) if entity_type is not None else None

    async def _init_event_capability_defaults(self) -> None:
        """Seed event caps with Idle / not-ringing so they are not null at start."""
        for capability_id in self.get_capabilities():
            if self.get_capability_value(capability_id) is not None:
                continue
            if capability_id.startswith("alarm_doorbell."):
                await self.set_capability_value(capability_id, False)
            elif capability_id.startswith(("event_button.", "event_generic.")):
                await self.set_capability_value(capability_id, "idle")

    def _get_on_off_capabilities(self) -> list[str]:
        """Indexed onoff caps only — bare ``onoff`` is registered separately."""
        return [
            capability_id
            for capability_id in self.get_capabilities()
            if capability_id.startswith("onoff.")
        ]

    def _get_button_capabilities(self) -> list[str]:
        return [
            capability_id
            for capability_id in self.get_capabilities()
            if capability_id.startswith(("button.", "restart", "identify"))
        ]

    def _get_number_capabilities(self) -> list[str]:
        """Settable Number entities only — sensors reuse esphome_number as read-only."""
        return [
            capability_id
            for capability_id in self.get_capabilities()
            if capability_id.startswith("esphome_number.")
            and self.get_capability_options(capability_id).get("setable", False)
        ]

    def _get_select_capabilities(self) -> list[str]:
        return [
            capability_id
            for capability_id in self.get_capabilities()
            if capability_id.startswith("esphome_select.")
        ]

    def _listener_with_capability_id(
        self,
        handler: Callable[..., Awaitable[None]],
        capability_id: str,
        *,
        pass_value: bool = True,
    ) -> CapabilityListener:
        """Bind ``capability_id`` so one handler can serve indexed capabilities."""

        if pass_value:

            async def listener(value: Any, **_kwargs: Any) -> None:
                await handler(value, capability_id=capability_id)

            return listener

        async def listener(_value: Any = True, **_kwargs: Any) -> None:
            await handler(capability_id=capability_id)

        return listener

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
            on_state=self._on_entity_state,
            on_connected=self._on_client_connected,
            on_disconnected=self._on_client_disconnected,
            on_connect_error=self._on_client_connect_error,
            debug=self.debug,
            error=self.error,
            deep_sleep=self.get_setting("deep_sleep") == "Yes",
        )
        await self._client.start()

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
        self._expected_disconnect = True
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
        """Keep deep-sleep devices available after an expected disconnect."""
        info = self._client.device_info if self._client is not None else None
        return info is not None and info.has_deep_sleep and self._expected_disconnect

    async def _on_client_disconnected(self, expected: bool) -> None:
        self._expected_disconnect = expected
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
        """Return the live session, or raise if the node is not connected."""
        if self._client is None or not self._client.available:
            raise RuntimeError(self.homey.translate("errors.device_not_connected"))
        return self._client

    async def _on_capability_onoff(
        self,
        value: Any,
        capability_id: str = "onoff",
        **_kwargs: Any,
    ) -> None:
        key = self._get_entity_key(capability_id)
        entity_type = self._get_entity_type(capability_id)
        client = self._require_client()

        if entity_type == "light":
            client.command("light_command", key, state=bool(value))
            return
        if entity_type == "fan":
            client.command("fan_command", key, state=bool(value))
            return
        if entity_type == "valve":
            client.command("valve_command", key, position=1.0 if value else 0.0)
            return
        if entity_type == "climate":
            if value:
                client.command(
                    "climate_command",
                    key,
                    mode=ClimateMode(
                        int(
                            self.get_capability_options(capability_id)[
                                "climate_on_mode"
                            ]
                        )
                    ),
                )
            else:
                client.command("climate_command", key, mode=ClimateMode.OFF)
            return
        if entity_type == "water_heater":
            client.command("water_heater_command", key, on=bool(value))
            return
        if entity_type == "siren":
            client.command("siren_command", key, state=bool(value))
            return
        if entity_type == "switch":
            client.command("switch_command", key, bool(value))
            return

        raise ValueError(f"Unsupported entity type for onoff: {entity_type}")

    async def _on_capability_button(
        self, *, capability_id: str, **_kwargs: Any
    ) -> None:
        self._require_client().command(
            "button_command", self._get_entity_key(capability_id)
        )

    async def _on_capability_number(
        self,
        value: Any,
        *,
        capability_id: str,
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "number_command",
            self._get_entity_key(capability_id),
            float(value),
        )

    async def _on_capability_select(
        self,
        value: Any,
        *,
        capability_id: str,
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "select_command",
            self._get_entity_key(capability_id),
            str(value),
        )

    async def _on_capability_windowcoverings_state(
        self,
        value: Any,
        capability_id: str = "windowcoverings_state",
        **_kwargs: Any,
    ) -> None:
        key = self._get_entity_key(capability_id)
        client = self._require_client()
        match value:
            case "up":
                client.command("cover_command", key, position=1.0)
            case "down":
                client.command("cover_command", key, position=0.0)
            case _:
                client.command("cover_command", key, stop=True)

    async def _on_capability_windowcoverings_set(
        self,
        value: Any,
        capability_id: str = "windowcoverings_set",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "cover_command",
            self._get_entity_key(capability_id),
            position=float(value),
        )

    async def _on_capability_windowcoverings_tilt_set(
        self,
        value: Any,
        capability_id: str = "windowcoverings_tilt_set",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "cover_command",
            self._get_entity_key(capability_id),
            tilt=float(value),
        )

    async def _on_capability_windowcoverings_tilt_up(
        self,
        _value: Any = True,
        capability_id: str = "windowcoverings_tilt_up",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "cover_command",
            self._get_entity_key(capability_id),
            tilt=1.0,
        )

    async def _on_capability_windowcoverings_tilt_down(
        self,
        _value: Any = True,
        capability_id: str = "windowcoverings_tilt_down",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "cover_command",
            self._get_entity_key(capability_id),
            tilt=0.0,
        )

    async def _on_capability_garagedoor_closed(
        self,
        value: Any,
        capability_id: str = "garagedoor_closed",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "cover_command",
            self._get_entity_key(capability_id),
            position=0.0 if value else 1.0,
        )

    async def _on_capability_thermostat_mode(
        self,
        value: Any,
        capability_id: str = "thermostat_mode",
        **_kwargs: Any,
    ) -> None:
        if str(value) == "auto":
            mode = ClimateMode(
                int(
                    self.get_capability_options(capability_id).get(
                        "climate_auto_mode",
                        int(ClimateMode.HEAT_COOL),
                    )
                )
            )
        else:
            mode = ClimateMode.__members__.get(str(value).upper(), ClimateMode.OFF)
        self._require_client().command(
            "climate_command",
            self._get_entity_key(capability_id),
            mode=mode,
        )

    async def _on_capability_thermostat_preset(
        self,
        value: Any,
        capability_id: str = "thermostat_preset",
        **_kwargs: Any,
    ) -> None:
        preset = ClimatePreset.__members__.get(str(value).upper())
        if preset is not None and str(value) == preset.name.lower():
            self._require_client().command(
                "climate_command",
                self._get_entity_key(capability_id),
                preset=preset,
            )
            return
        self._require_client().command(
            "climate_command",
            self._get_entity_key(capability_id),
            custom_preset=str(value),
        )

    async def _on_capability_homealarm_state(
        self,
        value: Any,
        capability_id: str = "homealarm_state",
        **_kwargs: Any,
    ) -> None:
        options = self.get_capability_options(capability_id)

        if value == "disarmed":
            command = AlarmControlPanelCommand.DISARM
        elif value == "armed":
            command = AlarmControlPanelCommand(int(options["alarm_armed_command"]))
        elif value == "partially_armed":
            command = AlarmControlPanelCommand(int(options["alarm_partial_command"]))
        else:
            self.error("Invalid homealarm_state", value)
            return

        self._require_client().command(
            "alarm_control_panel_command",
            self._get_entity_key(capability_id),
            command,
        )

    async def _on_capability_heater_operation_mode(
        self,
        value: Any,
        capability_id: str = "heater_operation_mode",
        **_kwargs: Any,
    ) -> None:
        mode = WaterHeaterMode.__members__.get(
            str(value).upper(),
            WaterHeaterMode.OFF,
        )
        self._require_client().command(
            "water_heater_command",
            self._get_entity_key(capability_id),
            mode=int(mode),
        )

    async def _on_capability_target_temperature(
        self,
        value: Any,
        capability_id: str = "target_temperature",
        **_kwargs: Any,
    ) -> None:
        key = self._get_entity_key(capability_id)
        temperature = self._entity_temperature(capability_id, value)
        client = self._require_client()
        if self._get_entity_type(capability_id) == "water_heater":
            client.command("water_heater_command", key, target_temperature=temperature)
            return
        client.command("climate_command", key, target_temperature=temperature)

    async def _on_capability_target_temperature_min(
        self,
        value: Any,
        capability_id: str = "target_temperature_min",
        **_kwargs: Any,
    ) -> None:
        key = self._get_entity_key(capability_id)
        temperature = self._entity_temperature(capability_id, value)
        client = self._require_client()
        if self._get_entity_type(capability_id) == "water_heater":
            client.command(
                "water_heater_command", key, target_temperature_low=temperature
            )
            return
        client.command("climate_command", key, target_temperature_low=temperature)

    async def _on_capability_target_temperature_max(
        self,
        value: Any,
        capability_id: str = "target_temperature_max",
        **_kwargs: Any,
    ) -> None:
        key = self._get_entity_key(capability_id)
        temperature = self._entity_temperature(capability_id, value)
        client = self._require_client()
        if self._get_entity_type(capability_id) == "water_heater":
            client.command(
                "water_heater_command", key, target_temperature_high=temperature
            )
            return
        client.command("climate_command", key, target_temperature_high=temperature)

    async def _on_capability_target_humidity(
        self,
        value: Any,
        capability_id: str = "target_humidity",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "climate_command",
            self._get_entity_key(capability_id),
            target_humidity=float(value),
        )

    async def _on_capability_swing_mode(
        self,
        value: Any,
        capability_id: str = "swing_mode",
        **_kwargs: Any,
    ) -> None:
        match str(value):
            case "both":
                swing_mode = ClimateSwingMode.BOTH
            case "horizontal":
                swing_mode = ClimateSwingMode.HORIZONTAL
            case "vertical":
                swing_mode = ClimateSwingMode.VERTICAL
            case _:
                swing_mode = ClimateSwingMode.OFF
        self._require_client().command(
            "climate_command",
            self._get_entity_key(capability_id),
            swing_mode=swing_mode,
        )

    async def _on_capability_fan_speed(
        self,
        value: Any,
        capability_id: str = "fan_speed",
        **_kwargs: Any,
    ) -> None:
        key = self._get_entity_key(capability_id)
        speed = float(value)
        speed_count = int(self.get_capability_options(capability_id)["speed_count"])
        speed_level = round(speed * speed_count)
        client = self._require_client()
        if speed_level > 0:
            client.command("fan_command", key, state=True, speed_level=speed_level)
        else:
            client.command("fan_command", key, state=False)

    async def _on_capability_fan_oscillate(
        self,
        value: Any,
        capability_id: str = "fan_oscillate",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "fan_command",
            self._get_entity_key(capability_id),
            oscillating=bool(value),
        )

    async def _on_capability_fan_mode(
        self,
        value: Any,
        capability_id: str = "fan_mode",
        **_kwargs: Any,
    ) -> None:
        key = self._get_entity_key(capability_id)
        entity_type = self._get_entity_type(capability_id)
        client = self._require_client()
        if entity_type == "climate":
            fan_mode = ClimateFanMode.__members__.get(str(value).upper())
            if fan_mode is not None and str(value) == fan_mode.name.lower():
                client.command("climate_command", key, fan_mode=fan_mode)
            else:
                client.command("climate_command", key, custom_fan_mode=str(value))
            return
        client.command("fan_command", key, preset_mode=_capitalize_preset(str(value)))

    async def _on_capability_aircleaner_mode(
        self,
        value: Any,
        capability_id: str = "aircleaner_mode",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "fan_command",
            self._get_entity_key(capability_id),
            preset_mode=_capitalize_preset(str(value)),
        )

    async def _on_capability_speaker_playing(
        self,
        value: Any,
        capability_id: str = "speaker_playing",
        **_kwargs: Any,
    ) -> None:
        key = self._get_entity_key(capability_id)
        client = self._require_client()
        if value:
            client.command("media_player_command", key, command=MediaPlayerCommand.PLAY)
            return
        if self.get_capability_options(capability_id)["supports_pause"]:
            client.command(
                "media_player_command", key, command=MediaPlayerCommand.PAUSE
            )
            return
        client.command("media_player_command", key, command=MediaPlayerCommand.STOP)

    async def _on_capability_speaker_stop(
        self,
        _value: Any = True,
        capability_id: str = "speaker_stop",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "media_player_command",
            self._get_entity_key(capability_id),
            command=MediaPlayerCommand.STOP,
        )

    async def _on_capability_volume_set(
        self,
        value: Any,
        capability_id: str = "volume_set",
        **_kwargs: Any,
    ) -> None:
        key = self._get_entity_key(capability_id)
        volume = float(value)
        client = self._require_client()
        if self._get_entity_type(capability_id) == "siren":
            client.command("siren_command", key, volume=volume)
            return
        client.command("media_player_command", key, volume=volume)

    async def _on_capability_volume_mute(
        self,
        value: Any,
        capability_id: str = "volume_mute",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "media_player_command",
            self._get_entity_key(capability_id),
            command=(MediaPlayerCommand.MUTE if value else MediaPlayerCommand.UNMUTE),
        )

    async def _on_capability_volume_up(
        self,
        _value: Any = True,
        capability_id: str = "volume_up",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "media_player_command",
            self._get_entity_key(capability_id),
            command=MediaPlayerCommand.VOLUME_UP,
        )

    async def _on_capability_volume_down(
        self,
        _value: Any = True,
        capability_id: str = "volume_down",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "media_player_command",
            self._get_entity_key(capability_id),
            command=MediaPlayerCommand.VOLUME_DOWN,
        )

    async def _on_capability_locked(
        self,
        value: Any,
        capability_id: str = "locked",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "lock_command",
            self._get_entity_key(capability_id),
            LockCommand.LOCK if value else LockCommand.UNLOCK,
        )

    async def _on_capability_valve_position(
        self,
        value: Any,
        capability_id: str = "valve_position",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "valve_command",
            self._get_entity_key(capability_id),
            position=float(value),
        )

    def _entity_temperature(self, capability_id: str, value: Any) -> float:
        """Convert Homey °C to the entity's configured temperature unit."""
        unit = str(self.get_capability_options(capability_id)["esphome_unit"])
        return convert_temperature_from_celsius(unit, float(value))

    async def _on_capability_dim(
        self,
        value: Any,
        capability_id: str = "dim",
        **_kwargs: Any,
    ) -> None:
        key = self._get_entity_key(capability_id)
        client = self._require_client()
        brightness = float(value)
        if brightness > 0:
            client.command("light_command", key, state=True, brightness=brightness)
        else:
            client.command("light_command", key, state=False)

    async def _on_capability_light_mode(
        self,
        value: Any,
        **_kwargs: Any,
    ) -> None:
        if value == "color":
            if self.has_capability("light_hue"):
                await self.trigger_capability_listener(
                    "light_hue",
                    self.get_capability_value("light_hue"),
                )
        elif value == "temperature":
            if self.has_capability("light_temperature"):
                await self.trigger_capability_listener(
                    "light_temperature",
                    self.get_capability_value("light_temperature"),
                )

    async def _on_capability_light_effect(
        self,
        value: Any,
        capability_id: str = "light_effect",
        **_kwargs: Any,
    ) -> None:
        self._require_client().command(
            "light_command",
            self._get_entity_key(capability_id),
            state=True,
            effect=str(value),
        )

    async def _on_capability_light_temperature(
        self,
        value: Any,
        capability_id: str = "light_temperature",
        **_kwargs: Any,
    ) -> None:
        if self.has_capability("light_mode"):
            await self.set_capability_value("light_mode", "temperature")

        options = self.get_capability_options(capability_id)
        min_kelvin = int(options["min_color_temp_kelvin"])
        max_kelvin = int(options["max_color_temp_kelvin"])
        kelvin = min_kelvin + (1 - float(value)) * (max_kelvin - min_kelvin)
        if kelvin <= 0:
            raise ValueError("Invalid color temperature")

        self._require_client().command(
            "light_command",
            self._get_entity_key(capability_id),
            state=True,
            color_mode=int(ColorMode.COLOR_TEMPERATURE),
            color_temperature=kelvin_to_mireds(kelvin),
        )

    async def _on_capability_light_hue_saturation(
        self,
        values: Mapping[str, Any],
        **_kwargs: Any,
    ) -> None:
        # The listener runs before Homey commits capability state; read from values.
        hue = (
            values["light_hue"]
            if "light_hue" in values
            else self.get_capability_value("light_hue")
        )
        sat = (
            values["light_saturation"]
            if "light_saturation" in values
            else self.get_capability_value("light_saturation")
        )

        if self.has_capability("light_mode"):
            await self.set_capability_value("light_mode", "color")

        red, green, blue = colorsys.hsv_to_rgb(
            float(hue) if hue is not None else 0.0,
            float(sat) if sat is not None else 0.0,
            1.0,
        )
        self._require_client().command(
            "light_command",
            self._get_entity_key("light_hue"),
            state=True,
            color_mode=int(ColorMode.RGB),
            color_brightness=1.0,
            rgb=(red, green, blue),
        )


def _capitalize_preset(value: str) -> str:
    """Homey enum ids are lowercase; ESPHome presets are titled."""
    return value[:1].upper() + value[1:]
