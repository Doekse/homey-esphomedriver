"""Driver logic for pairing ESPHome nodes discovered on the LAN."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from aioesphomeapi import APIConnectionError, EncryptionPlaintextAPIError
from homey.discovery_result_mdns_sd import DiscoveryResultMDNSSD
from homey.discovery_strategy import DiscoveryStrategy
from homey.driver import Driver, ListDeviceProperties
from homey.pair_session import PairSession

from homey_esphomedriver.entities.mapping import DeviceEntityMapper
from homey_esphomedriver.esphome_client import (
    DEFAULT_API_PORT,
    probe_esphome_device,
)
from homey_esphomedriver.esphome_types import HomeyEspHomeDeviceOption
from homey_esphomedriver.esphome_util import (
    attach_library_logs,
    debug_log,
    error_key,
    invalid_encryption_key,
    needs_encryption_key,
    normalize_mac,
)
from homey_esphomedriver.flow import DriverFlowHandler
from homey_esphomedriver.improv_ble import ImprovBleClient, ImprovError
from homey_esphomedriver.profile import BrandProfile

_MDNS_WAIT_TIMEOUT_S = 12.0
"""Seconds to wait for mDNS after BLE Improv.

Kept well under Homey's ~30s pair-emit timeout because BLE setup already
used some of that budget.
"""
_MDNS_POLL_S = 2.0


class EspHomeDriver(Driver):
    """
    Homey driver for pairing and driving ESPHome nodes on the LAN.

    Extend this class and export it from ``driver.py`` as ``homey_export``.
    Override :meth:`on_esphome_init` / :meth:`on_esphome_uninit` instead of
    :meth:`on_init` / :meth:`on_uninit`. Product filters come from the driver
    manifest ``esphome`` object; a class-level :attr:`brand_profile` overrides
    that when Python-only hooks such as ``after_map`` are needed.

    Homey's stock ``add_devices`` template only creates the list_devices
    selection, so pairing finishes in a custom ``add_device`` view that calls
    ``get_device`` and ``Homey.createDevice`` with the mapped payload.
    BLE Improv only puts the node on Wi-Fi, then pairing returns to
    ``list_devices`` so the user picks it over mDNS like any other node.

    Example:
        ```python
        from homey_esphomedriver import EspHomeDriver

        homey_export = EspHomeDriver
        ```
    """

    _flow: DriverFlowHandler

    @property
    def brand_profile(self) -> BrandProfile:
        """Resolved product profile: class attribute, else compose ``esphome``."""
        resolved = getattr(self, "_resolved_brand_profile", None)
        if resolved is not None:
            return resolved
        assigned = vars(type(self)).get("brand_profile")
        if isinstance(assigned, BrandProfile):
            resolved = assigned
        else:
            resolved = BrandProfile.from_manifest(self.manifest)
        self._resolved_brand_profile = resolved
        return resolved

    async def on_init(self) -> None:
        """Wire Flow listeners and library logs.

        Do not override. Use :meth:`on_esphome_init` for brand setup.
        """
        await super().on_init()
        attach_library_logs(self.log, self.error)
        self._flow = DriverFlowHandler(self)
        self._flow.register()
        await self.on_esphome_init()
        self.log("Initialized EspHomeDriver")

    async def on_uninit(self) -> None:
        """Tear down brand hooks, then the Homey driver.

        Do not override. Use :meth:`on_esphome_uninit` for brand cleanup.
        """
        await self.on_esphome_uninit()
        await super().on_uninit()

    async def on_esphome_init(self) -> None:
        """Brand hook after Flow listeners are registered.

        Do not override :meth:`on_init`.
        """

    async def on_esphome_uninit(self) -> None:
        """Brand hook before core teardown.

        Do not override :meth:`on_uninit`.
        """

    def debug(self, *args: object) -> None:
        """Write a debug log line when ``DEBUG`` is enabled in ``env.json``."""
        debug_log(self.log, *args)

    async def on_pair(self, session: PairSession) -> None:
        """Wire multi-step pair views for discovery, BLE Improv, and encryption."""
        selected: dict[str, Any] | None = None
        host: str | None = None
        port: int = DEFAULT_API_PORT
        noise_psk: str | None = None
        mapped_device: HomeyEspHomeDeviceOption | None = None
        listing_ble = False
        peripheral_uuid: str | None = None
        improv_client: ImprovBleClient | None = None

        def pair_improv_client() -> ImprovBleClient:
            """Reuse one Improv client for the pair session."""
            nonlocal improv_client
            if improv_client is None:
                improv_client = ImprovBleClient(self.homey, debug=self.debug)
            return improv_client

        async def on_list_devices(
            _view_data: Any = None,
        ) -> list[ListDeviceProperties]:
            """Return mDNS results, fallback rows, or BLE Improv peripherals."""
            if listing_ble:
                return await self._list_improv_pair_devices(pair_improv_client())

            devices = self._list_discovery_devices()
            devices.append(
                {
                    "name": self.homey.translate("pair.list.add_by_ip"),
                    "data": {"id": "manual"},
                    "icon": "/icon-ip.svg",
                    "capabilities": [],
                }
            )
            if self.homey.has_permission("homey:wireless:ble"):
                devices.append(
                    {
                        "name": self.homey.translate("pair.list.setup_bluetooth"),
                        "data": {"id": "ble-setup"},
                        "icon": "/icon-bluetooth.svg",
                        "capabilities": [],
                    }
                )
            return devices

        async def on_list_devices_selection(devices: list[dict[str, Any]]) -> None:
            """Capture the chosen discovery or BLE row before the next step."""
            nonlocal selected, host, port, noise_psk, mapped_device, peripheral_uuid
            if not devices:
                raise ValueError(self.homey.translate("errors.no_device_selected"))

            selected = devices[0]
            mapped_device = None
            noise_psk = None
            selected_id = selected.get("data", {}).get("id")
            store = selected.get("store") or {}

            if selected_id in ("manual", "ble-setup"):
                host = None
                peripheral_uuid = None
                if selected_id == "manual":
                    port = DEFAULT_API_PORT
                return

            ble_uuid = store.get("peripheralUuid")
            if listing_ble or ble_uuid:
                host = None
                peripheral_uuid = str(ble_uuid or selected_id)
                return

            peripheral_uuid = None
            host = store.get("address") or store.get("host")
            port = int(store.get("port") or DEFAULT_API_PORT)

        async def on_show_view(view_id: str) -> None:
            """Route loading: BLE scan, manual IP, encryption key, or connect+map."""
            nonlocal mapped_device, listing_ble

            if view_id == "list_ble_devices":
                listing_ble = True
                return
            if view_id == "list_devices":
                listing_ble = False
                await close_improv()
                return
            if view_id != "loading":
                return

            if selected is None:
                raise ValueError(self.homey.translate("errors.no_device_selected"))

            selected_id = selected.get("data", {}).get("id")
            if selected_id == "ble-setup":
                listing_ble = True
                await session.show_view("list_ble_devices")
                return

            if selected_id == "manual" and not host:
                await session.show_view("configure_manual")
                return

            if not host:
                raise ValueError(self.homey.translate("errors.host_required"))

            try:
                mapped_device = await self._connect_and_map(
                    host=host,
                    port=port,
                    noise_psk=noise_psk,
                    expected_id=(None if selected_id == "manual" else str(selected_id)),
                )
            except Exception as err:
                mapped_device = None
                if needs_encryption_key(err):
                    await session.show_view("enter_key")
                    if noise_psk or invalid_encryption_key(err):
                        raise ValueError(self.homey.translate(error_key(err))) from err
                    return

                self.error("ESPHome pair connect failed", err)
                if isinstance(err, ValueError):
                    raise
                raise ValueError(self.homey.translate(error_key(err))) from err

            await session.show_view("add_device")

        async def on_configure_manual(data: dict[str, Any]) -> str:
            """Store host/port and return the next pair view id."""
            nonlocal host, port, mapped_device
            host, port = self._parse_manual_connection(data)
            mapped_device = None
            return "loading"

        async def on_enter_wifi(data: dict[str, Any]) -> str:
            """Provision Wi-Fi over BLE Improv and return the mDNS list view id."""
            nonlocal selected, host, noise_psk, mapped_device, listing_ble
            nonlocal peripheral_uuid
            if not peripheral_uuid:
                raise ValueError(
                    self.homey.translate("errors.bluetooth_device_required")
                )
            ssid = str(data.get("ssid") or "").strip()
            if not ssid:
                raise ValueError(self.homey.translate("errors.ssid_required"))
            password = str(data.get("password") or "")

            known_ids = {
                str(device.get("data", {}).get("id") or "")
                for device in self._list_discovery_devices()
            }

            client = pair_improv_client()
            try:
                await client.connect(peripheral_uuid)
                await client.send_wifi(ssid, password)
            except Exception as err:
                await client.close()
                self.error("ESPHome BLE Improv failed", err)
                key = (
                    err.key
                    if isinstance(err, ImprovError)
                    else "errors.improv.bluetooth_connect"
                )
                raise ValueError(self.homey.translate(key)) from err

            await close_improv()
            await self._wait_for_new_discovery(known_ids)

            selected = None
            host = None
            noise_psk = None
            mapped_device = None
            listing_ble = False
            peripheral_uuid = None
            return "list_devices"

        async def on_enter_key(data: dict[str, Any]) -> str:
            """Store the Noise PSK and return the next pair view id."""
            nonlocal noise_psk, mapped_device
            raw_key = str(data.get("noise_psk") or "").strip()
            if not raw_key:
                raise ValueError(self.homey.translate("errors.encryption_key_required"))

            noise_psk = raw_key
            mapped_device = None
            return "loading"

        async def on_get_device(_data: Any = None) -> HomeyEspHomeDeviceOption:
            """Return the mapped device for the custom add_device view."""
            if mapped_device is None:
                raise RuntimeError(self.homey.translate("errors.device_not_prepared"))
            if not mapped_device["capabilities"]:
                raise RuntimeError(self.homey.translate("errors.no_supported_entities"))
            return mapped_device

        async def close_improv(_data: Any = None) -> None:
            """Drop any in-progress Improv GATT session."""
            nonlocal improv_client
            client = improv_client
            improv_client = None
            if client is not None:
                await client.close()

        session.set_handler("list_devices", on_list_devices)
        session.set_handler("list_devices_selection", on_list_devices_selection)
        session.set_handler("list_ble_devices_selection", on_list_devices_selection)
        session.set_handler("showView", on_show_view)
        session.set_handler("configure_manual", on_configure_manual)
        session.set_handler("enter_wifi", on_enter_wifi)
        session.set_handler("enter_key", on_enter_key)
        session.set_handler("get_device", on_get_device)
        session.set_handler("disconnect", close_improv)

    async def on_repair(self, session: PairSession, device: Any) -> None:
        """Update host/port, prompting for a Noise PSK only when the node needs it."""
        host = ""
        port = DEFAULT_API_PORT
        noise_psk = str(device.get_store().get("noise_psk") or "").strip() or None
        expected_id = str(device.get_data()["id"])

        async def connection_values(_data: Any = None) -> dict[str, str]:
            store = device.get_store()
            port_value = device.get_setting("port") or store.get("port")
            return {
                "mac": str(
                    device.get_setting("mac") or store.get("mac") or expected_id
                ),
                "host": str(
                    device.get_setting("host") or store.get("address") or ""
                ).strip(),
                "port": "" if port_value in (None, "") else str(port_value),
            }

        async def on_show_view(view_id: str) -> None:
            if view_id == "configure_manual":
                await session.emit("prefill", await connection_values())

        async def probe_and_finish(psk: str | None) -> None:
            try:
                info, _, _ = await probe_esphome_device(
                    host,
                    port,
                    noise_psk=psk,
                    client_info=self.brand_profile.client_info,
                    debug=self.debug,
                )
            except EncryptionPlaintextAPIError:
                if psk:
                    await probe_and_finish(None)
                    return
                raise
            if normalize_mac(info.mac_address) != normalize_mac(expected_id):
                raise ValueError(self.homey.translate("errors.device_mismatch"))
            await device.apply_connection(host=host, port=port, noise_psk=psk)
            await session.done()

        async def try_connect(psk: str | None, *, prompt_key: bool) -> str | None:
            try:
                await probe_and_finish(psk)
            except Exception as err:
                self.error("ESPHome repair connect failed", err)
                if prompt_key and needs_encryption_key(err):
                    return "enter_key"
                if isinstance(err, ValueError):
                    raise
                raise ValueError(self.homey.translate(error_key(err))) from err
            return None

        async def on_configure_manual(data: dict[str, Any]) -> str | None:
            nonlocal host, port
            host, port = self._parse_manual_connection(data)
            return await try_connect(noise_psk, prompt_key=True)

        async def on_enter_key(data: dict[str, Any]) -> str | None:
            nonlocal noise_psk
            raw_key = str(data.get("noise_psk") or "").strip()
            if not raw_key:
                raise ValueError(self.homey.translate("errors.encryption_key_required"))
            noise_psk = raw_key
            return await try_connect(noise_psk, prompt_key=False)

        session.set_handler("get_connection", connection_values)
        session.set_handler("showView", on_show_view)
        session.set_handler("configure_manual", on_configure_manual)
        session.set_handler("enter_key", on_enter_key)

    def _list_discovery_devices(self) -> list[ListDeviceProperties]:
        """Build list_devices rows from Homey's mDNS discovery strategy."""
        discovery_strategy = self.get_discovery_strategy()
        if discovery_strategy is None:
            return []

        typed_strategy = cast(
            DiscoveryStrategy[DiscoveryResultMDNSSD],
            discovery_strategy,
        )
        discovery_results = typed_strategy.get_discovery_results()
        paired_ids = {
            normalize_mac(str(device.get_data().get("id") or ""))
            for device in self.get_devices()
        }

        devices: list[ListDeviceProperties] = []
        for discovery_result in discovery_results.values():
            if normalize_mac(discovery_result.id) in paired_ids:
                continue
            if not self.brand_profile.accepts_discovery(discovery_result.txt):
                continue

            friendly_name = discovery_result.txt.get("friendly_name")
            devices.append(
                {
                    "name": friendly_name or discovery_result.name or "ESPHome Device",
                    "data": {"id": discovery_result.id},
                    "store": {
                        "address": discovery_result.address,
                        "host": discovery_result.host,
                        "port": discovery_result.port or DEFAULT_API_PORT,
                    },
                    "capabilities": [],
                }
            )

        return devices

    async def _list_improv_pair_devices(
        self,
        client: ImprovBleClient,
    ) -> list[ListDeviceProperties]:
        """Scan Homey's BLE radio for Improv peripherals."""
        try:
            found = await client.discover()
        except Exception as err:
            self.error("ESPHome BLE Improv scan failed", err)
            raise ValueError(self.homey.translate("errors.improv.scan_failed")) from err

        if not found:
            raise ValueError(self.homey.translate("errors.improv.none_found"))

        return [
            {
                "name": device["name"],
                "data": {"id": device["uuid"]},
                "store": {"peripheralUuid": device["uuid"]},
                "capabilities": [],
            }
            for device in found
        ]

    async def _wait_for_new_discovery(self, known_ids: set[str]) -> None:
        """Give Homey's mDNS cache a moment to see the provisioned node."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _MDNS_WAIT_TIMEOUT_S
        while loop.time() < deadline:
            for device in self._list_discovery_devices():
                device_id = str(device.get("data", {}).get("id") or "")
                if device_id and device_id not in known_ids:
                    return
            await asyncio.sleep(_MDNS_POLL_S)

    def _parse_manual_connection(self, data: dict[str, Any]) -> tuple[str, int]:
        """Return host and port from the IP form."""
        raw_host = str(data.get("host") or "").strip()
        if not raw_host:
            raise ValueError(self.homey.translate("errors.host_required"))

        raw_port = data.get("port", DEFAULT_API_PORT)
        try:
            parsed_port = int(raw_port)
        except (TypeError, ValueError) as err:
            raise ValueError(self.homey.translate("errors.port_number")) from err
        if parsed_port < 1 or parsed_port > 65535:
            raise ValueError(self.homey.translate("errors.port_range"))

        return raw_host, parsed_port

    async def _connect_and_map(
        self,
        *,
        host: str,
        port: int,
        noise_psk: str | None,
        expected_id: str | None,
    ) -> HomeyEspHomeDeviceOption:
        """Probe the node, map entities, and build the Homey device payload."""
        try:
            self.debug(f"Probing {host}:{port} encrypted={noise_psk is not None}")
            device_info, entities, _services = await probe_esphome_device(
                host,
                port,
                noise_psk=noise_psk,
                client_info=self.brand_profile.client_info,
                debug=self.debug,
            )
        except APIConnectionError:
            raise
        except Exception as err:
            raise ValueError(self.homey.translate("errors.cannot_connect")) from err

        if not self.brand_profile.accepts_project(device_info.project_name):
            raise ValueError(self.homey.translate("errors.project_not_supported"))

        device_id = normalize_mac(device_info.mac_address)
        if not device_id:
            raise ValueError(self.homey.translate("errors.mac_missing"))

        if expected_id and normalize_mac(expected_id) != normalize_mac(device_id):
            raise ValueError(self.homey.translate("errors.device_mismatch"))

        # Homey discovery matches paired devices by this id; keep the mDNS form.
        data_id = expected_id or device_id

        homey_device = DeviceEntityMapper.pair_option(
            device_info,
            host=host,
            port=port,
            noise_psk=noise_psk,
            data_id=data_id,
        )

        try:
            DeviceEntityMapper.map_device(
                entities, homey_device, profile=self.brand_profile
            )
        except Exception as err:
            self.error("Failed to map ESPHome entities", data_id, err)
            raise ValueError(self.homey.translate("errors.cannot_connect")) from err

        if not homey_device.get("class"):
            # Homey requires a class; mapping leaves it unset when no entity claims one.
            homey_device["class"] = "other"
        homey_device["store"]["auto_class"] = homey_device["class"]

        self.debug(
            f"Mapped {homey_device['name']} ({data_id}) to "
            f"{len(homey_device['capabilities'])} capabilities, "
            f"class={homey_device['store']['auto_class']}"
        )
        return homey_device
