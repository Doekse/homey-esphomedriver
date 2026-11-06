"""Test bootstrap.

The device module imports the Homey SDK, which is not installed in CI.
Provide the few classes the import needs so device tests can run.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any, Generic, TypeVar

import pytest

_DriverT = TypeVar("_DriverT")


def _install_homey_stub() -> None:
    try:
        import homey.device  # noqa: F401
    except ModuleNotFoundError:
        pass
    else:
        return

    class Device(Generic[_DriverT]):
        def get_name(self) -> str:
            return self._name

    class Driver:
        pass

    homey = types.ModuleType("homey")
    device = types.ModuleType("homey.device")
    discovery = types.ModuleType("homey.discovery_result")
    mdns = types.ModuleType("homey.discovery_result_mdns_sd")
    driver = types.ModuleType("homey.driver")
    pair = types.ModuleType("homey.pair_session")
    device.Device = Device
    discovery.DiscoveryResult = type("DiscoveryResult", (), {})
    mdns.DiscoveryResultMDNSSD = type("DiscoveryResultMDNSSD", (), {})
    driver.Driver = Driver
    pair.PairSession = type("PairSession", (), {})
    homey.device = device
    homey.discovery_result = discovery
    homey.discovery_result_mdns_sd = mdns
    homey.driver = driver
    homey.pair_session = pair
    sys.modules.update(
        {
            "homey": homey,
            "homey.device": device,
            "homey.discovery_result": discovery,
            "homey.discovery_result_mdns_sd": mdns,
            "homey.driver": driver,
            "homey.pair_session": pair,
        }
    )


_install_homey_stub()


_DRIVER_COMPOSE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "homey_esphomedriver"
    / "homey_template"
    / "compose"
    / "drivers"
)


def expand_setting(setting: dict[str, Any]) -> dict[str, Any]:
    """Resolve a top-level setting ``$extends`` the way Homey Compose does.

    Homey spreads the template over ``{"id": template_id}`` and the setting's
    own keys over that, so a template's ``id`` wins over the template id.
    """
    template_id = setting.get("$extends")
    if template_id is None:
        return setting
    path = _DRIVER_COMPOSE / "settings" / f"{template_id}.json"
    template = json.loads(path.read_text(encoding="utf-8"))
    own = {key: value for key, value in setting.items() if key != "$extends"}
    return {"id": setting.get("$id", template_id), **template, **own}


@pytest.fixture
def default_settings() -> list[dict[str, Any]]:
    """The ``esphome-defaults`` settings with every ``$extends`` resolved."""
    path = _DRIVER_COMPOSE / "templates" / "esphome-defaults.json"
    template = json.loads(path.read_text(encoding="utf-8"))
    return [expand_setting(setting) for setting in template["settings"]]
