"""Bootstrap naming-helper tests.

Covers driver-id validation and the derived Homey / ESPHome identifiers used
when scaffolding a brand app. Does not write files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from homey_esphomedriver.bootstrap import (
    _validate_driver_id,
    derive_app_id,
    derive_app_name,
    derive_brand,
    derive_project_name,
    profile_constant,
)


def test_profile_constant_uppercases_hyphens() -> None:
    assert profile_constant("aq-1") == "AQ_1_PROFILE"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (Path("/apps/airgradient-homey"), "com.airgradient"),
        (Path("/apps/Brand App"), "com.brandapp"),
    ],
)
def test_derive_app_id(path: Path, expected: str) -> None:
    assert derive_app_id(path) == expected


@pytest.mark.parametrize(
    ("path", "explicit", "expected"),
    [
        (Path("/apps/airgradient-homey"), None, "Airgradient"),
        (Path("/apps/x"), "AirGradient", "AirGradient"),
    ],
)
def test_derive_app_name(path: Path, explicit: str | None, expected: str) -> None:
    assert derive_app_name(path, explicit) == expected


@pytest.mark.parametrize(
    ("app_name", "explicit", "expected"),
    [
        ("Air Gradient", None, "AirGradient"),
        ("ignored", "Brand", "Brand"),
    ],
)
def test_derive_brand(app_name: str, explicit: str | None, expected: str) -> None:
    assert derive_brand(app_name, explicit) == expected


@pytest.mark.parametrize(
    ("brand", "driver_id", "explicit", "expected"),
    [
        ("Brand", "aq-1", None, "Brand.AQ-1"),
        ("Brand", "aq-1", "Brand.Custom", "Brand.Custom"),
    ],
)
def test_derive_project_name(
    brand: str,
    driver_id: str,
    explicit: str | None,
    expected: str,
) -> None:
    assert derive_project_name(brand, driver_id, explicit) == expected


@pytest.mark.parametrize("driver_id", ["aq-1", "esphome-device", "a"])
def test_validate_driver_id_accepts(driver_id: str) -> None:
    _validate_driver_id(driver_id)


@pytest.mark.parametrize("driver_id", ["AQ-1", "aq_1", "-aq", "aq-", "aq 1", ""])
def test_validate_driver_id_rejects(driver_id: str) -> None:
    with pytest.raises(ValueError, match="Invalid driver id"):
        _validate_driver_id(driver_id)
