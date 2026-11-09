# Homey ESPHomeDriver

[![PyPI version](https://img.shields.io/pypi/v/homey-esphomedriver)](https://pypi.org/project/homey-esphomedriver/)
[![PyPI downloads](https://img.shields.io/pypi/dm/homey-esphomedriver)](https://pypi.org/project/homey-esphomedriver/)
[![Python](https://img.shields.io/badge/python-3.14-3776AB?logo=python&logoColor=white)](https://pypi.org/project/homey-esphomedriver/)
[![CI](https://img.shields.io/github/actions/workflow/status/Doekse/homey-esphomedriver/ci.yml?branch=main)](https://github.com/Doekse/homey-esphomedriver/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
![Status](https://img.shields.io/badge/status-alpha-orange.svg)
[![Homey](https://img.shields.io/badge/Homey-Python_SDK_v3-00C9FF.svg)](https://apps.developer.homey.app/)

This module can be used to make the development of ESPHome apps for Homey easier.

It is essentially a map-tool from Homey-capabilities to ESPHome entities.

This module requires Homey Apps SDK v3.

## Related Modules

- [node-homey-zigbeedriver](https://athombv.github.io/node-homey-zigbeedriver) — Module for Zigbee drivers
- [node-homey-zwavedriver](https://athombv.github.io/node-homey-zwavedriver) — Module for Z-Wave drivers
- [node-homey-rfdriver](https://athombv.github.io/node-homey-rfdriver) — Module for RF drivers
- [node-homey-oauth2app](https://athombv.github.io/node-homey-oauth2app) — Module for OAuth2 apps



## Installation

```bash
$ pip install homey-esphomedriver
```

Homey apps declare it next to `aioesphomeapi` in `app.json` / `.homeycompose/app.json`:

```json
"pythonPackages": ["aioesphomeapi", "homey-esphomedriver"]
```

Also checkout `[aioesphomeapi](https://github.com/esphome/aioesphomeapi)` if you want to talk to the ESPHome Native API directly, without `homey-esphomedriver`.

```bash
$ pip install aioesphomeapi
```



## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## Requirements

This module requires Homey Apps SDK v3 (Python 3.14 runtime).

## Usage

Your device should extend `EspHomeDevice`. This is the class you most likely want to extend from. Your driver should extend `EspHomeDriver`.

Like Z-Wave and Zigbee drivers, a driver declares its capabilities in `driver.compose.json`, and the device binds each one to an ESPHome entity in `on_esphome_init`. The library knows how to read and set Homey's system capabilities on each ESPHome domain; anything else is your own code.

### Driver compose

```json
{
  "name": { "en": "AQ-1" },
  "class": "sensor",
  "capabilities": ["measure_temperature", "measure_co2", "onoff.led", "dim.led", "button.calibrate"],
  "capabilitiesOptions": {
    "onoff.led": { "title": { "en": "Status LED" } },
    "dim.led": { "title": { "en": "Status LED brightness" } },
    "button.calibrate": {
      "maintenanceAction": true,
      "title": { "en": "Calibrate CO₂" },
      "desc": { "en": "Place the sensor outside for 10 minutes first" }
    }
  },
  "$extends": ["esphome-defaults"],
  "esphome": {
    "clientInfo": "Homey EverythingSmart",
    "projects": ["EverythingSmart.AQ-1"]
  }
}
```

| `esphome` key   | Purpose                                                         |
| --------------- | --------------------------------------------------------------- |
| `projects`      | Exact ESPHome `project.name` this driver accepts                |
| `projectPrefix` | Prefix match such as `Brand.`                                   |
| `clientInfo`    | Name shown on the node for this Homey client                    |
| `nativeApps`    | Suggest a dedicated Homey app for a project (`io.esphome` only) |

Omit `projects` / `projectPrefix` to accept every project (`io.esphome`). If both are set, either match is enough. Any other key is logged and ignored.

A button for a rare or risky task, such as a calibration, goes in the device's Maintenance menu with Homey's own `maintenanceAction` capability option, as above.

### Device

```python
# drivers/aq-1/device.py
from homey_esphomedriver import EspHomeDevice


class Aq1Device(EspHomeDevice):
    async def on_esphome_init(self, client):
        self.register_capability("measure_temperature", "sensor", "Temperature")
        self.register_capability("measure_co2", "sensor", "CO2")
        self.register_capability("onoff.led", "light", "Status LED")
        self.register_capability("dim.led", "light", "Status LED")
        self.register_capability("button.calibrate", "button", "Calibrate CO2")


homey_export = Aq1Device
```

`register_capability(capability_id, domain, name, *, device_id=0, set_parser=None, report_parser=None)` follows Z-Wave's `registerCapability`:

- The capability must already be on the device; registering never adds one. A missing capability raises `ValueError`.
- An entity is named by its ESPHome domain and its name, as written in the YAML, plus `device_id` for a sub-device. `object_id` is not used: ESPHome plans to remove it.
- System capabilities supply the parsers, looked up by the full id and then its base, as Z-Wave splits on the dot: `dim.led` uses `dim`.
- `sensor`, `binary_sensor`, `text_sensor`, `number`, `select`, `switch`, `text`, `button` and `event` entities bind to any capability without a parser, including your own. A sensor's reading is converted from the entity's unit to the capability's (°F to °C, kW to W, …).
- `sensor`, `binary_sensor`, `text_sensor` and `event` entities only report, so they do not bind to a Homey capability the user can set, such as `onoff`, `locked` or `target_temperature`, without a parser. Homey would show a control that cannot work.
- On other domains, a capability the library does not know raises `ValueError` unless you pass a parser.
- Bindings are made again on every app start and resolved on every connection, before the state dump. An entity the node does not have is logged and its capability left alone; setting it fails with a message.

| System capabilities | Domain |
| --- | --- |
| `homealarm_state` | `alarm_control_panel` |
| any `alarm_*`, `battery_charging_state` | `binary_sensor` |
| `onoff`, `thermostat_mode`, `measure_temperature`, `target_temperature`, `target_temperature_min`, `target_temperature_max`, `measure_humidity`, `target_humidity`, `fan_mode`, `swing_mode` | `climate` |
| `windowcoverings_state`, `windowcoverings_set`, `windowcoverings_tilt_set`, `windowcoverings_tilt_up`, `windowcoverings_tilt_down`, `garagedoor_closed` | `cover` |
| `onoff`, `fan_speed`, `fan_mode` | `fan` |
| `onoff`, `dim`, `light_mode`, `light_hue`, `light_saturation`, `light_temperature` | `light` |
| `locked`, `alarm_door_fault` | `lock` |
| `speaker_playing`, `speaker_stop`, `volume_set`, `volume_mute`, `volume_up`, `volume_down` | `media_player` |
| `onoff`, `volume_set` | `siren` |
| `onoff`, `valve_position` | `valve` |
| `onoff`, `heater_operation_mode`, `measure_temperature`, `target_temperature`, `target_temperature_min`, `target_temperature_max` | `water_heater` |

`light_hue` and `light_saturation` are sent together in one command once both are bound to the same light, as `ZwaveLightDevice` does.

[CAPABILITIES.md](CAPABILITIES.md) has how each capability maps, the sensor unit conversions and what is not supported.

#### Parsers

Pass a parser to change how a value is read or set, or for an app capability on a multi-value domain:

```python
self.register_capability(
    "aq1_air_quality",
    "sensor",
    "VOC Index",
    report_parser=lambda state, entity: "poor" if state.state > 150 else "good",
)
self.register_capability(
    "onoff.led",
    "light",
    "Status LED",
    set_parser=lambda value, opts, entity: {"state": value, "effect": "Pulse"},
)
```

- `report_parser(state, entity)` turns the ESPHome state into the capability value. `None` leaves the capability as is. A missing reading, NaN or Infinity is written as unknown before the parser runs.
- `set_parser(value, opts, entity)` returns the keyword arguments for the domain's command, here `light_command`. `None` sends nothing; an exception is shown to the user.
- `entity` is the bound entity: `entity.info` is what the node listed (unit, color temperature range, speed count, …) and `entity.capability_value("light_hue")` reads a sibling capability.

#### Everything else

What no capability shows is your own code, like Z-Wave's `registerReportListener`:

```python
class Aq1Device(EspHomeDevice):
    async def on_esphome_init(self, client):
        self.register_state_listener("event", "Button", self._on_button)

    async def _on_button(self, state, entity):
        card = self.homey.flow.get_device_trigger_card("aq1_button_pressed")
        await card.trigger(self, {"type": state.event_type})
```

`self.entity(domain, name)` gives the entity of the current connection, to send it a command yourself through `self.client.command("<domain>_command", entity.key, ...)`. `unregister_capability(capability_id)` stops reporting and setting a capability you remove at runtime.

### Driver

```python
# drivers/aq-1/driver.py
from homey_esphomedriver import EspHomeDriver

homey_export = EspHomeDriver
```

A new device gets the driver's capabilities. To choose them from what the node has, as the generic ESPHome app does, override `on_pair_device(device, device_info, entities)` and set `capabilities`, `capabilitiesOptions` or `class` on the payload it returns.

### Settings

`esphome-defaults` brings the device information settings, which the library writes. A driver that declares its own `settings` replaces that list (Homey Compose does not merge it), so it keeps the group through its setting template and adds its own around it:

```json
"settings": [
  { "type": "group", "label": { "en": "Calibration" }, "children": [ ... ] },
  { "$extends": "esphome-device-information" }
]
```

A driver that leaves it out fails on init with an error naming the `$extends` to add.

### Lifecycle hooks

Core owns `on_init` and `on_uninit` on `EspHomeDriver` and `EspHomeDevice`. Subclass the hooks below instead — same pattern as `homey-oauth2app`'s `onOAuth2Init`. Brand `app.py` exports Homey's `App`.

| Class           | Override                                        | When                                                                |
| --------------- | ----------------------------------------------- | ------------------------------------------------------------------- |
| `EspHomeDriver` | `on_esphome_init` / `on_esphome_uninit`         | After the manifest check, e.g. to register Flow cards / before teardown |
| `EspHomeDriver` | `on_pair_device(device, device_info, entities)` | Before Homey creates a paired device                                |
| `EspHomeDevice` | `on_esphome_init(client)` / `on_esphome_uninit` | Before the session starts; `client` is `None` when host is unknown  |
| `EspHomeDevice` | `on_esphome_connected(client)`                  | After each login + `set_available`; session not READY yet — no cmds |

On a paired device, use `self.client` for the live `EspHomeClient` (may exist before the API handshake). Commands require a READY session — including from `on_esphome_connected`.

Debug logging uses `env.json` `DEBUG`; there is no separate class flag.

### Homey Compose files

Homey Compose runs before Python, so `$extends` / `$template` only see files already in the app. When `homey-esphomedriver` is listed in `pythonPackages`, Homey CLI copies this package's templates into `.homeycompose/` during preprocess (`homey app run`, `build`, `validate`), before compose. That is what makes `"$extends": ["esphome-defaults"]` and pair `"$template": "enter_key"` resolve.

Until that CLI is released, or when the package is unpublished, run the same copy by hand:

```bash
$ esphome-homey sync
```

`-p` / `--path` selects an app directory other than the current one. `sync` leaves `app.json`, `app.py`, `driver.compose.json`, and existing driver code alone unless `--force`.

A brand app is a normal Homey Python app:

```bash
$ homey app create
$ homey app dependencies add aioesphomeapi homey-esphomedriver
$ homey app driver create
```

Then set `$extends` and the `esphome` block on each driver's `driver.compose.json`, add store images, and publish with Homey CLI.

## Documentation

See [ARCHITECTURE.md](ARCHITECTURE.md) for what devices get from Homey and how a brand listing is an `esphome` compose block on top of this core.

- `[esphome-homey](https://github.com/Doekse/esphome-homey)` — generic Homey app (`io.esphome`; any ESPHome node)



## License

MIT. See [LICENSE](LICENSE).