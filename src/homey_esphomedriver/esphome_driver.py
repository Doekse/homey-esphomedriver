"""Homey Driver for ESPHome brand apps.

Wires :class:`~homey_esphomedriver.flow.DriverFlowHandler` and
:class:`~homey_esphomedriver.pairing.DriverPairHandler`. Homey lifecycle stays
here; Flow cards and pair/repair wizards live on those handlers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homey.driver import Driver
from homey.pair_session import PairSession

from homey_esphomedriver.esphome_util import (
    attach_library_logs,
    debug_log,
)
from homey_esphomedriver.flow import DriverFlowHandler
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
    manifest ``esphome`` object; a class-level :attr:`brand_profile` overrides
    that when Python-only hooks such as ``after_map`` are needed.

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
        await DriverPairHandler(self).pair(session)

    async def on_repair(self, session: PairSession, device: EspHomeDevice) -> None:
        """Update host/port, prompting for a Noise PSK only when the node needs it."""
        await DriverPairHandler(self).repair(session, device)
