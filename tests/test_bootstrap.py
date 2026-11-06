"""Bootstrap tests.

Covers driver-id validation, the derived Homey / ESPHome identifiers used when
scaffolding a brand app, and the shared setting templates it copies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from homey_esphomedriver.bootstrap import (
    BootstrapResult,
    _copy_shared,
    _validate_driver_id,
    derive_app_id,
    derive_app_name,
    derive_brand,
    derive_project_name,
    template_root,
)


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


def test_default_settings_expand_to_the_full_settings_page(
    default_settings: list[dict[str, Any]],
) -> None:
    """Splitting the groups into setting templates keeps every setting."""
    assert [group.get("id") for group in default_settings] == [
        "esphome-device",
        "esphome-device-capabilities",
        "notifications",
        "device_information",
    ]
    leaves = [child for group in default_settings for child in group["children"]]
    assert [setting["id"] for setting in leaves] == [
        "device_class",
        "show_diagnostics",
        "show_configuration",
        "notify_entities_changed",
        "host",
        "port",
        "encryption",
        "manufacturer",
        "model",
        "mac",
        "hostname",
        "esphome_version",
        "compilation_time",
        "project",
        "bluetooth_mac",
        "webserver",
        "deep_sleep",
    ]


def test_sync_copies_setting_templates(tmp_path: Path) -> None:
    """A brand driver with its own settings pulls the default groups from here."""
    _copy_shared(template_root(), tmp_path, BootstrapResult())

    copied = tmp_path / ".homeycompose" / "drivers" / "settings"
    assert sorted(path.name for path in copied.iterdir()) == [
        "esphome-device-capabilities.json",
        "esphome-device-information.json",
        "esphome-device-notifications.json",
        "esphome-device.json",
    ]
