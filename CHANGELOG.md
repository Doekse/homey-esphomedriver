# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] - 2026-11-05

### Added

- Post a timeline notification when an automatic firmware sync adds or removes entities, so you can check your Flows. Devices paired before the checkbox existed stay opted in, and a manual Refresh does not notify.
- Sync Homey capabilities when a node reconnects with different firmware: add capabilities for new entities and remove capabilities for entities that are gone, without pressing Refresh. A reconnect with the same firmware does not list entities.
- Provision a Noise encryption key over the zero-PSK handshake during pair/repair when the node is unprovisioned, instead of asking the user to paste one.
- Repair starts on a Maintenance page: Repair Device (existing IP/key flow) or Show Key (copy the stored Noise PSK).
- Accept shell-style patterns in `hiddenEntities`, so a family of entities can be hidden by `debug_*` rather than enumerated.

### Changed

- Fetch only DeviceInfo when the Native API session connects, instead of also listing every entity on each reconnect and deep-sleep wake; initial states arrive sooner because the firmware no longer finishes a listing first.
- Only write the Device Information settings on login when a value changed, instead of a Homey settings round-trip on every reconnect and deep-sleep wake.
- Only write the address, port and hostname to the device store and settings when discovery reports a different value, instead of four Homey round-trips per device on every app start.
- Feed newly discovered IPs into the running Native API client instead of tearing down the session on every mDNS address change.
- Apply each ESPHome entity state inline instead of scheduling an asyncio task per state, so states for hidden entities cost a dict lookup and mapped states skip a task hop. Entity state handlers' `handle()` is now synchronous; start a task for any awaited work.
- After a failed dial or an unexpected drop, wait for Homey discovery to see the node again instead of retrying the last stored IP, and log the failure as one line.
- Require aioesphomeapi 46.25.0. Each device no longer starts its own zeroconf (mDNS) stack after a failed connect; Homey's discovery events now kick a pending connect via `notify_device_seen()`, which also stops each sighting from resetting the reconnect backoff.

### Removed

- `bootstrap.profile_constant()`, which nothing called.

### Fixed

- Drop and reconnect the Native API session right away when Homey rediscovers a node that rebooted without a goodbye, instead of showing it available until the keepalive times out.
- Treat unpublished ESPHome switch, climate, and water-heater state as unknown Homey values instead of off / 0 °C.
- Write NaN and Infinity as unknown for every capability instead of sending them to Homey, where a climate entity reporting NaN before its first reading could crash the Homey SHS main process (#15).
- Skip Flow triggers when an entity state goes unknown, instead of firing "turned false", sending "None", or raising on `float(None)`.
- Mark a deep-sleep node unavailable after a failed dial or an unexpected drop; only a goodbye before sleep keeps it available.

## [0.4.1] - 2026-08-28

### Fixed

- Enable Continue on the encryption-key and Wi-Fi pair views after typing or autofill on iOS (do not use the HTML ``disabled`` attribute).
- List discovered devices during pairing without raising ``NameError: DiscoveryStrategy is not defined``.
- Close the repair session from the view after a successful repair; awaiting ``session.done()`` inside a custom emit handler deadlocks Homey's pair client, which 0.4.0 fixed for ``show_view`` but not for ``done``.

## [0.4.0] - 2026-08-22

### Added

- Map ESPHome lock ``supports_open`` to an ``open`` button that sends ``LockCommand.OPEN`` (door strike / unlatch).
- Offer a generic Press Flow card for suffixed ``button.*`` capabilities.
- Add missing custom capability icons.
- Add ``on_esphome_connected`` so brand devices can run setup after each Native API login.

### Changed

- Map lock ``JAMMED`` to Homey ``alarm_door_fault`` instead of ``alarm_stuck``.

### Fixed

- Pair and repair custom views navigate after their emit resolves, instead of awaiting ``show_view`` from inside the handler (Homey pair-client deadlock on Continue).
- Enable Continue on the encryption-key and Wi-Fi pair views when the field is already filled (autofill / load).
- Fill diagnostic and configuration capabilities from last known states when they are added.
- Offer generic Flow cards for suffixed custom capabilities by adding a hidden bare id Homey's ``$filter`` can match.
- Refresh capabilities installs and drops pair-time Flow-filter markers the same way pairing does.
- Reject capability commands until the Native API session is READY, so Homey cannot write default values on pair or reconnect.
- Register hue/saturation command listeners once so Homey's grouped listener does not log already-registered.
- Derive the ``in/d`` speed divisor from ``in/h`` instead of a standalone constant.
- Treat stored ``None`` capability options as empty so Refresh and init do not raise.

## [0.3.0] - 2026-08-19

### Added

- Maintenance action **Refresh capabilities** remaps the live node: unchanged entities keep their Homey ids, new ones are added, gone or remapped ones are removed.

### Fixed

- Keep Homey's system titles on bare climate capabilities instead of repeating the ESPHome entity name on every row.
- Skip climate ``fan_mode`` updates that are not in the device's picker values.
- Do not mark a Homey device unavailable when the Native API session is stopped on purpose (delete, unload, repair).

## [0.2.0] - 2026-08-19

### Added

- Declare `energy.batteries` as `INTERNAL` so Homey publish validation accepts `alarm_battery` / `measure_battery`.
- Map ESPHome climate presets onto a `thermostat_preset` picker, with Flow cards to react to and set the preset.

### Changed

- Stop setting a pairing icon from Homey device class. Devices keep the driver icon; users can pick Homey's icon override.
- Show "Repair the device" with a subtitle on the first repair view.
- Expose climate fan speeds and custom fan modes on `fan_mode` instead of collapsing them to auto/on/off.
- Use Homey's system `fan_mode` and `fan_speed` instead of custom capability copies.

### Fixed

- Log Homey connect/disconnect callback failures instead of leaving them as unhandled task exceptions.
- Map climate Dry and Fan-only onto `thermostat_mode` instead of treating them as off.

## [0.1.0] - 2026-08-18

### Added

- `EspHomeDriver` and `EspHomeDevice` for Homey Apps SDK v3.
- Mapping of ESPHome entities to Homey capabilities (light, switch, sensor, binary sensor, cover, climate, fan, lock, button, number, select, media player, valve, siren, event, alarm panel, water heater).
- Pairing over mDNS, IP, encryption key, and BLE Improv.
- Brand product filters via the driver compose `esphome` object.
- `esphome-homey sync` to copy Homey Compose templates into the app.

[unreleased]: https://github.com/Doekse/homey-esphomedriver/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/Doekse/homey-esphomedriver/releases/tag/v0.5.0
[0.4.1]: https://github.com/Doekse/homey-esphomedriver/releases/tag/v0.4.1
[0.4.0]: https://github.com/Doekse/homey-esphomedriver/releases/tag/v0.4.0
[0.3.0]: https://github.com/Doekse/homey-esphomedriver/releases/tag/v0.3.0
[0.2.0]: https://github.com/Doekse/homey-esphomedriver/releases/tag/v0.2.0
[0.1.0]: https://github.com/Doekse/homey-esphomedriver/releases/tag/v0.1.0
