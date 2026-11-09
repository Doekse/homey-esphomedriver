# Architecture

`homey-esphomedriver` is the shared layer between ESPHome devices and Homey. It does for ESPHome what `homey-zwavedriver` and `homey-zigbeedriver` do for their protocols: a driver declares its capabilities, and the device binds each one to what the node exposes. The generic `[esphome-homey](https://github.com/Doekse/esphome-homey)` app (`io.esphome`) builds its catch-all mapping on top of the same API; brand apps declare only the capabilities of their products.

Brands don't need to reimplement discovery, encryption, the Native API, reconnect logic or BLE Wi-Fi setup. They declare their products, bind their capabilities, add the store assets and ship the app.

```text
ESPHome firmware                    Homey
─────────────────                   ─────
project.name = Brand.AQ-1           Brand app  (drivers, capabilities, own Flow cards)
        │                                    │
        │  Native API (TCP :6053)            │  pythonPackages
        └────────────►  homey-esphomedriver  ◄┘
                        discovery, pairing, reconnect,
                        register_capability + system capabilities,
                        Improv BLE
```

## What this does for ESPHome devices

Homey talks directly to the device using ESPHome's Native API. Everything stays local, without a cloud in between.

| Device need              | What core provides                                                                                               |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------- |
| Find the node on the LAN | mDNS discovery, plus add-by-IP when discovery doesn't find it                                                    |
| First-time Wi-Fi         | BLE Improv provisioning. Once connected, the device appears through mDNS like any other ESPHome node             |
| Secure API               | Noise encryption key during pairing or repair. Reconnect stops when the key is wrong instead of endlessly retrying |
| Capabilities             | `register_capability` with system capability parsers per Homey capability and ESPHome domain                     |
| Stay connected           | Reconnect after connection loss, follow mDNS address changes and keep deep-sleep devices available while offline |

## Capabilities, the Z-Wave way

| homey-zwavedriver                                          | homey-esphomedriver                                       |
| ---------------------------------------------------------- | --------------------------------------------------------- |
| Capabilities declared in `driver.compose.json`             | Same; registering never adds one                          |
| `registerCapability('onoff', 'SWITCH_BINARY', opts)`       | `register_capability("onoff", "switch", "Relay", **opts)` |
| Command class                                              | ESPHome entity domain                                     |
| `reportParser(report)` / `setParser(value, opts)`          | `report_parser(state, entity)` / `set_parser(value, opts, entity)` |
| `lib/system/capabilities/<cap>/<CC>.js`                    | `system/<domain>.py`, a `CAPABILITIES` table per domain   |
| `registerReportListener(cc, report, fn)`                   | `register_state_listener(domain, name, fn)`               |
| `onNodeInit`                                               | `on_esphome_init`                                         |

An entity is named by its domain and its name, plus a `device_id` for a sub-device: the identity aioesphomeapi's newest unique ids use. `object_id` is derived from the name, collides for non-ASCII names and sub-devices, and is planned for removal in ESPHome.

`bindings.py` keeps the bindings in memory; they are made again on every app start, as in Z-Wave. Each login fetches the device info and the entity list in one request, resolves every binding, and only then subscribes to states, so the connect dump reaches every bound capability. A binding to an entity the node lacks is logged; setting that capability fails with a message.

`system/__init__.py` looks a capability up by its full id, then its base (`dim.led` finds `dim`, as Z-Wave splits on the dot), then the domain's `default`, which single-value domains such as `sensor` and `number` have for any capability. Parsers get the bound entity, so metadata such as a sensor's unit, a light's color temperature range or a fan's speed count comes from what the node listed, not from capability options stored at pair time. The library writes unknown for a missing reading, NaN or Infinity before a report parser runs, so a parser's `None` can mean "leave it as is", as in Z-Wave. A set parser returns keyword arguments for `<domain>_command`. A `MULTI` group, such as hue and saturation, is set in one debounced command, like `ZwaveLightDevice`.

## What this does for brands

A dedicated Homey app gives users the app they would actually expect to search for in the Homey App Store. For example, `Apollo Automation` or `Everything Presence` instead of `ESPHome`.

Typical setup:

1. Create a Homey Python app: `homey app create`
2. Add the packages: `homey app dependencies add aioesphomeapi homey-esphomedriver`
3. Copy Compose templates: `esphome-homey sync`
4. Add one Homey driver per product: `homey app driver create`
5. Set `$extends: ["esphome-defaults"]`, `esphome.projects` and the product's `capabilities` in `driver.compose.json`
6. Bind the capabilities in the device's `on_esphome_init`
7. Add the product names, icons and PNG store images, and publish using the Homey CLI

Homey CLI does not copy these templates yet. `esphome-homey sync` writes them into `.homeycompose/`; commit that output so `homey app run` works on a stock CLI. Re-run `sync` after a core upgrade.

### Driver manifest (compose `esphome`)

Normally there is one Homey driver per product SKU. Product filters go on that driver's `driver.compose.json`, the same place Zigbee puts `manufacturerName` / `productId`. Homey's driver schema allows extra keys, so `esphome` survives `homey app validate` and is available at runtime as `self.manifest["esphome"]`.

| Compose key     | What a brand uses it for                                                                                         |
| --------------- | ---------------------------------------------------------------------------------------------------------------- |
| `projects`      | Only allow specific firmware on this driver, for example `Brand.AQ-1`                                            |
| `projectPrefix` | Match all projects using a prefix such as `Brand.`. Less common, but useful when several products share a driver |
| `clientInfo`    | Name shown on the ESPHome device for the connected client, for example `Homey Brand`                             |
| `nativeApps`    | `io.esphome` only: suggest the dedicated Homey app for a project                                                 |

If both `projects` and `projectPrefix` are configured, a match on either is enough. If neither is configured, every ESPHome project is accepted. This is how `io.esphome` works.

There is nothing to hide or remap: a device shows the capabilities its driver declares. A rare or risky button goes in the Maintenance menu with Homey's own `maintenanceAction` capability option.

### Pairing

Pairing probes the node, checks its project, and creates the device with its connection in the store and settings. The payload has no `capabilities`, so Homey gives the device the driver's own. `EspHomeDriver.on_pair_device` may set `capabilities`, `capabilitiesOptions` and `class` from what the node has; `io.esphome` maps every entity there.

### Lifecycle hooks

`EspHomeDriver` and `EspHomeDevice` seal `on_init` / `on_uninit`. Brand apps extend `on_esphome_init`, `on_esphome_connected`, and `on_esphome_uninit` instead (mirrors `homey-oauth2app`). Brand `app.py` exports Homey's `App`.

On `EspHomeDevice`, `on_esphome_init(client)` is where capabilities and state listeners are registered, like Z-Wave's `onNodeInit`. It runs before the API session starts, so no state or ready event arrives during it. `client` is `None` when the node has no host yet (waiting on mDNS).

`on_esphome_connected(client)` runs at the end of each successful login (including reconnects), after Homey `set_available()`. The session is still not READY when the hook runs — `_mark_ready()` happens after `_on_connected` returns — so brand code must not issue commands until `client.available`.

### What the brand owns vs what core owns

| Brand app                                                      | This package                                                       |
| -------------------------------------------------------------- | ------------------------------------------------------------------ |
| Store listing, app ID, product names and images                | Native API client and reconnect logic                              |
| One driver folder per SKU, with its capabilities               | `register_capability` and the system capability parsers            |
| Its own custom capabilities and Flow cards                     | Improv BLE, encryption and mDNS/IP pairing                         |
| `esphome` block in `driver.compose.json`                       | Compose defaults, pairing UI and locales (`esphome-homey sync`)    |

`esphome-homey sync` refreshes the Homey files owned by the package after a core upgrade. It does not overwrite `app.json`, `app.py` or existing `driver.py` / `device.py` files unless `--force` is explicitly used, and it never deletes files.

## Two app shapes, one core

|               | Generic `io.esphome`                            | Brand `{brand}-homey`                        |
| ------------- | ----------------------------------------------- | -------------------------------------------- |
| Who it is for | Any ESPHome node                                | Products from that manufacturer              |
| Drivers       | One catch-all driver                            | One driver per product SKU                   |
| Capabilities  | Mapped from every entity at pairing, kept in sync with the firmware | Declared per driver, bound in `on_esphome_init` |
| Filter        | None                                            | Exact `project.name` matching per driver     |
| Store         | “ESPHome”                                       | The brand name users already know            |

Firmware should set ESPHome `project.name`, for example `Brand.AQ-1`. That value is what the brand driver uses to recognize its own hardware. It also allows the generic ESPHome app to point users towards the dedicated Homey app when one is available.
