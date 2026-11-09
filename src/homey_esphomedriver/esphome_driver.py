"""Homey Driver for ESPHome brand apps.

Wires :class:`~homey_esphomedriver.pairing.DriverPairHandler`. Homey lifecycle
stays here; the pair and repair wizards live on that handler.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from aioesphomeapi import DeviceInfo, EntityInfo
from homey.driver import Driver
from homey.pair_session import PairSession

from homey_esphomedriver.esphome_types import HomeyEspHomeDeviceOption
from homey_esphomedriver.esphome_util import (
    attach_library_logs,
    debug_log,
    missing_default_settings,
)
from homey_esphomedriver.pairing import DriverPairHandler
from homey_esphomedriver.profile import BrandProfile

if TYPE_CHECKING:
    from homey_esphomedriver.esphome_device import EspHomeDevice


class EspHomeDriver(Driver):
    """
    Homey driver for pairing and driving ESPHome nodes on the LAN.

    Extend this class and export it from ``driver.py`` as ``homey_export``.
    Override :meth:`on_esphome_init` / :meth:`on_esphome_uninit` instead of
    :meth:`on_init` / :meth:`on_uninit`. Product filters come from the driver
    manifest ``esphome`` object; a device's capabilities are the driver's own.

    Example:
        ```python
        from homey_esphomedriver import EspHomeDriver

        homey_export = EspHomeDriver
        ```
    """

    @property
    def brand_profile(self) -> BrandProfile:
        """Product profile built from the driver manifest's ``esphome`` object."""
        resolved = getattr(self, "_resolved_brand_profile", None)
        if resolved is None:
            resolved = BrandProfile.from_manifest(self.manifest)
            self._resolved_brand_profile = resolved
        return resolved

    async def on_init(self) -> None:
        """Check the manifest and wire library logs.

        Do not override. Use :meth:`on_esphome_init` for brand setup.
        """
        await super().on_init()
        _reject_assigned_profile(type(self))
        _require_default_settings(self.manifest)
        attach_library_logs(self.log, self.error)
        await self.on_esphome_init()
        self.log("Initialized EspHomeDriver")

    async def on_uninit(self) -> None:
        """Tear down brand hooks, then the Homey driver.

        Do not override. Use :meth:`on_esphome_uninit` for brand cleanup.
        """
        await self.on_esphome_uninit()
        await super().on_uninit()

    async def on_esphome_init(self) -> None:
        """Brand hook for driver setup, such as registering Flow cards.

        Do not override :meth:`on_init`.
        """

    async def on_esphome_uninit(self) -> None:
        """Brand hook before core teardown.

        Do not override :meth:`on_uninit`.
        """

    def debug(self, *args: object) -> None:
        """Write a debug log line when ``DEBUG`` is enabled in ``env.json``."""
        debug_log(self.log, *args)

    async def on_pair_device(
        self,
        device: HomeyEspHomeDeviceOption,
        device_info: DeviceInfo,
        entities: Sequence[EntityInfo],
    ) -> HomeyEspHomeDeviceOption:
        """Hook to adjust the device Homey creates when a node is paired.

        The payload has no ``capabilities``, so Homey gives the device the
        driver's own. Override to set ``capabilities``, ``capabilitiesOptions``
        or ``class`` from what the node has, as the generic ESPHome app does.

        Args:
            device: Pair payload with name, data, store and settings.
            device_info: The node's device info.
            entities: Entities the node listed.

        Returns:
            The payload to create the device from.
        """
        del device_info, entities
        return device

    async def on_pair(self, session: PairSession) -> None:
        """Wire multi-step pair views for discovery, BLE Improv, and encryption."""
        await DriverPairHandler(self).pair(session)

    async def on_repair(self, session: PairSession, device: EspHomeDevice) -> None:
        """Update host/port, prompting for a Noise PSK only when the node needs it."""
        await DriverPairHandler(self).repair(session, device)


def _require_default_settings(manifest: Mapping[str, Any] | None) -> None:
    """Fail on init when a driver's own ``settings`` dropped a default group.

    Homey Compose replaces the ``esphome-defaults`` settings when a driver
    declares ``settings``. The library reads and writes the default ones, so
    the brand must keep each group through its setting template.

    Raises:
        ValueError: Naming the missing settings and the ``$extends`` to add.
    """
    missing = missing_default_settings(manifest)
    if not missing:
        return
    driver_id = (manifest or {}).get("id", "?")
    detail = "; ".join(
        f'{{"$extends": "{template_id}"}} for {", ".join(setting_ids)}'
        for template_id, setting_ids in missing.items()
    )
    msg = (
        f"Driver {driver_id!r} declares settings without the ESPHome defaults. "
        f"Add to its settings: {detail}"
    )
    raise ValueError(msg)


def _reject_assigned_profile(driver_class: type) -> None:
    """Fail fast on a pre-0.6 class-level ``brand_profile = BrandProfile(...)``.

    Assigning it would shadow the property and silently ignore compose.
    """
    for klass in driver_class.__mro__:
        if isinstance(vars(klass).get("brand_profile"), BrandProfile):
            msg = (
                f"{klass.__name__}.brand_profile is no longer supported: move the "
                "data to the driver.compose.json esphome object"
            )
            raise TypeError(msg)
