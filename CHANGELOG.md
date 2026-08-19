# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Declare `energy.batteries` as `INTERNAL` so Homey publish validation accepts `alarm_battery` / `measure_battery`.
- Map ESPHome climate presets onto a `thermostat_preset` picker, with Flow cards to react to and set the preset.

### Changed

- Stop setting a pairing icon from Homey device class. Devices keep the driver icon; users can pick Homey's icon override.
- Show "Repair the device" with a subtitle on the first repair view.
- Expose climate fan speeds and custom fan modes on `fan_mode` instead of collapsing them to auto/on/off.

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

[unreleased]: https://github.com/Doekse/homey-esphomedriver/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Doekse/homey-esphomedriver/releases/tag/v0.1.0