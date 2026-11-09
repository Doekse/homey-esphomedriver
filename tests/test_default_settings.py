"""A driver that declares its own settings must keep the ESPHome defaults.

Homey Compose replaces the ``esphome-defaults`` settings when a driver lists
``settings``. The library reads and writes the default ones, so the driver
fails on init, naming the setting template to add, rather than misbehaving on
a user's device.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from homey_esphomedriver import esphome_util
from homey_esphomedriver.esphome_driver import _require_default_settings
from homey_esphomedriver.esphome_util import missing_default_settings

_LINKED = {
    "type": "group",
    "label": {"en": "Calibration"},
    "children": [
        {
            "id": "temp_offset",
            "type": "number",
            "esphome": {"domain": "number", "name": "Temperature offset"},
        }
    ],
}


def test_esphome_defaults_are_complete(default_settings: list[dict[str, Any]]) -> None:
    assert missing_default_settings({"settings": default_settings}) == {}


def test_brand_settings_that_keep_every_template_are_complete(
    default_settings: list[dict[str, Any]],
) -> None:
    settings = [_LINKED, *default_settings]
    _require_default_settings({"id": "aq-1", "settings": settings})


def test_dropped_group_is_named_by_its_template() -> None:
    missing = missing_default_settings({"settings": [_LINKED]})
    assert list(missing) == ["esphome-device-information"]
    assert "host" in missing["esphome-device-information"]


def test_driver_without_defaults_fails_on_init() -> None:
    with pytest.raises(ValueError) as raised:
        _require_default_settings({"id": "aq-1", "settings": [_LINKED]})
    message = str(raised.value)
    assert "'aq-1'" in message
    assert '{"$extends": "esphome-device-information"}' in message


@pytest.fixture
def fresh_defaults() -> Iterator[None]:
    """Re-read the default templates instead of the cached package copy."""
    esphome_util._default_setting_ids.cache_clear()
    yield
    esphome_util._default_setting_ids.cache_clear()


@pytest.mark.usefixtures("fresh_defaults")
def test_missing_package_data_fails_instead_of_passing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no templates to compare against, every driver would pass."""
    monkeypatch.setattr(esphome_util, "_DRIVER_COMPOSE", tmp_path)
    with pytest.raises(RuntimeError, match="esphome-defaults.json"):
        missing_default_settings({"settings": [_LINKED]})


@pytest.mark.usefixtures("fresh_defaults")
def test_missing_setting_template_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "esphome-defaults.json").write_text(
        '{"settings": [{"$extends": "esphome-device"}]}', "utf-8"
    )
    monkeypatch.setattr(esphome_util, "_DRIVER_COMPOSE", tmp_path)
    with pytest.raises(RuntimeError, match="esphome-device.json"):
        missing_default_settings({"settings": [_LINKED]})
