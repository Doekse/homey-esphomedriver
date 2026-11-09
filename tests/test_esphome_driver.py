"""EspHomeDriver profile resolution."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from aioesphomeapi import DeviceInfo

from homey_esphomedriver.esphome_driver import EspHomeDriver, _reject_assigned_profile
from homey_esphomedriver.profile import BrandProfile


def _driver(cls: type[EspHomeDriver], manifest: dict[str, object]) -> EspHomeDriver:
    driver = cls.__new__(cls)
    driver.manifest = manifest  # type: ignore[misc]
    return driver


def test_brand_profile_is_built_from_compose_once() -> None:
    driver = _driver(EspHomeDriver, {"esphome": {"projects": ["Brand.AQ-1"]}})

    profile = driver.brand_profile
    assert profile.projects == frozenset({"Brand.AQ-1"})
    assert driver.brand_profile is profile


def test_pair_device_hook_returns_the_payload_unchanged() -> None:
    driver = _driver(EspHomeDriver, {})
    payload: dict[str, Any] = {"name": "node", "data": {}, "store": {}, "settings": {}}
    result = asyncio.run(driver.on_pair_device(payload, DeviceInfo(), []))  # type: ignore[arg-type]
    assert result is payload
    assert "capabilities" not in result


def test_assigned_brand_profile_is_rejected() -> None:
    """A pre-0.6 class attribute would shadow the property and ignore compose."""

    class Driver(EspHomeDriver):
        brand_profile = BrandProfile(projects=frozenset({"Brand.AQ-1"}))  # type: ignore[assignment]

    with pytest.raises(TypeError, match="driver.compose.json"):
        _reject_assigned_profile(Driver)


def test_driver_without_assigned_profile_passes() -> None:
    _reject_assigned_profile(SimpleNamespace)
    _reject_assigned_profile(EspHomeDriver)
