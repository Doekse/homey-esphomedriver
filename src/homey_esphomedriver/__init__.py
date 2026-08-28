"""Shared ESPHome Native API client, entity mapping, and pairing for Homey apps.

Brand apps import :class:`EspHomeDriver` and :class:`EspHomeDevice` and re-export
them from ``driver.py`` / ``device.py``. Product filters live on the driver
manifest as ``esphome`` (see :class:`BrandProfile`).

Homey-dependent symbols load on first access so helpers such as
:mod:`homey_esphomedriver.bootstrap` import without the Homey SDK.
"""

from __future__ import annotations

from typing import Any

from homey_esphomedriver.profile import DEFAULT_BRAND_PROFILE, BrandProfile

__version__ = "0.4.1"

__all__ = [
    "BrandProfile",
    "DEFAULT_BRAND_PROFILE",
    "EspHomeClient",
    "EspHomeDevice",
    "EspHomeDriver",
    "__version__",
]


def __getattr__(name: str) -> Any:
    """Load Homey-dependent symbols on first access.

    Args:
        name: Attribute requested from this package.

    Returns:
        The matching class.

    Raises:
        AttributeError: If ``name`` is not a lazy export.
    """
    if name == "EspHomeClient":
        from homey_esphomedriver.esphome_client import EspHomeClient

        return EspHomeClient
    if name == "EspHomeDevice":
        from homey_esphomedriver.esphome_device import EspHomeDevice

        return EspHomeDevice
    if name == "EspHomeDriver":
        from homey_esphomedriver.esphome_driver import EspHomeDriver

        return EspHomeDriver
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
