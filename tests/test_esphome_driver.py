"""EspHomeDriver profile resolution."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from homey_esphomedriver.esphome_driver import EspHomeDriver, _reject_assigned_profile
from homey_esphomedriver.profile import BrandProfile


class _BrandProfile(BrandProfile):
    pass


def _driver(cls: type[EspHomeDriver], manifest: dict[str, object]) -> EspHomeDriver:
    driver = cls.__new__(cls)
    driver.manifest = manifest  # type: ignore[misc]
    return driver


def test_brand_profile_class_is_built_from_compose() -> None:
    class Driver(EspHomeDriver):
        brand_profile_class = _BrandProfile

    driver = _driver(Driver, {"esphome": {"projects": ["Brand.AQ-1"]}})

    profile = driver.brand_profile
    assert type(profile) is _BrandProfile
    assert profile.projects == frozenset({"Brand.AQ-1"})
    assert driver.brand_profile is profile


def test_assigned_brand_profile_is_rejected() -> None:
    """A pre-0.6 class attribute would shadow the property and ignore compose."""

    class Driver(EspHomeDriver):
        brand_profile = BrandProfile(projects=frozenset({"Brand.AQ-1"}))  # type: ignore[assignment]

    with pytest.raises(TypeError, match="brand_profile_class"):
        _reject_assigned_profile(Driver)


def test_driver_without_assigned_profile_passes() -> None:
    _reject_assigned_profile(SimpleNamespace)
    _reject_assigned_profile(EspHomeDriver)
