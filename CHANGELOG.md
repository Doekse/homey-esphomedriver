# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Stop setting a pairing icon from Homey device class. Devices keep the driver icon; users can pick Homey's icon override.

## [0.1.0] - 2026-08-18

### Added

- `EspHomeDriver` and `EspHomeDevice` for Homey Apps SDK v3.
- Mapping of ESPHome entities to Homey capabilities (light, switch, sensor, binary sensor, cover, climate, fan, lock, button, number, select, media player, valve, siren, event, alarm panel, water heater).
- Pairing over mDNS, IP, encryption key, and BLE Improv.
- Brand product filters via the driver compose `esphome` object.
- `esphome-homey sync` to copy Homey Compose templates into the app.

[unreleased]: https://github.com/Doekse/homey-esphomedriver/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Doekse/homey-esphomedriver/releases/tag/v0.1.0