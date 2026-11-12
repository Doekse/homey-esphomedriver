"""Bootstrap tests.

Covers driver-id validation, the derived Homey / ESPHome identifiers used when
scaffolding a brand app, and the shared setting templates it copies.
"""

from __future__ import annotations

import ast
import json
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
    derive_device_class_name,
    derive_project_name,
    main,
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
    assert [group.get("id") for group in default_settings] == ["device_information"]
    leaves = [child for group in default_settings for child in group["children"]]
    assert [setting["id"] for setting in leaves] == [
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
        "esphome-device-information.json",
    ]


def test_sync_leaves_capabilities_and_flow_cards_to_the_app(tmp_path: Path) -> None:
    _copy_shared(template_root(), tmp_path, BootstrapResult())

    assert not (tmp_path / ".homeycompose" / "capabilities").exists()
    assert not (tmp_path / ".homeycompose" / "flow").exists()
    assert not (tmp_path / "assets" / "capabilities").exists()


@pytest.mark.parametrize(
    ("driver_id", "expected"),
    [
        ("aq-1", "Aq1Device"),
        ("everything-presence-one", "EverythingPresenceOneDevice"),
        ("1pm", "EspHome1pmDevice"),
    ],
)
def test_derive_device_class_name(driver_id: str, expected: str) -> None:
    assert derive_device_class_name(driver_id) == expected
    assert expected.isidentifier()


def _registered_capabilities(device_py: str) -> list[str]:
    """Capability ids passed to ``register_capability`` in a device module."""
    return [
        node.args[0].value
        for node in ast.walk(ast.parse(device_py))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "register_capability"
    ]


def test_driver_command_scaffolds_a_bound_driver(tmp_path: Path) -> None:
    app_dir = tmp_path / "everythingsmart-homey"

    exit_code = main(
        ["driver", "aq-1", "-p", str(app_dir), "--project", "EverythingSmart.AQ-1"]
    )

    assert exit_code == 0
    driver_dir = app_dir / "drivers" / "aq-1"
    compose = json.loads((driver_dir / "driver.compose.json").read_text())
    assert compose["$extends"] == ["esphome-defaults"]
    assert compose["esphome"]["projects"] == ["EverythingSmart.AQ-1"]
    device_py = (driver_dir / "device.py").read_text()
    assert "class Aq1Device(EspHomeDevice):" in device_py
    assert "homey_export = Aq1Device" in device_py
    assert _registered_capabilities(device_py) == compose["capabilities"]
    assert "__" not in (driver_dir / "driver.compose.json").read_text()
    assert (app_dir / ".homeycompose" / "drivers" / "templates").is_dir()


def test_driver_command_defaults_the_project_to_the_app_name(tmp_path: Path) -> None:
    app_dir = tmp_path / "everythingsmart-homey"

    main(["driver", "aq-1", "-p", str(app_dir)])

    compose = json.loads((app_dir / "drivers/aq-1/driver.compose.json").read_text())
    assert compose["esphome"]["projects"] == ["Everythingsmart.AQ-1"]
    assert compose["esphome"]["clientInfo"] == "Homey Everythingsmart"


def test_driver_command_keeps_existing_driver_code(tmp_path: Path) -> None:
    device = tmp_path / "drivers" / "aq-1" / "device.py"
    device.parent.mkdir(parents=True)
    device.write_text("# mine\n")

    main(["driver", "aq-1", "-p", str(tmp_path)])
    assert device.read_text() == "# mine\n"

    main(["driver", "aq-1", "-p", str(tmp_path), "--force"])
    assert "register_capability" in device.read_text()


def test_driver_command_rejects_an_invalid_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["driver", "AQ_1", "-p", str(tmp_path)]) == 1
    assert "Invalid driver id" in capsys.readouterr().err
    assert not (tmp_path / "drivers").exists()
