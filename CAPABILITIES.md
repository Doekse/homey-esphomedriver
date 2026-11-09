# Supported capabilities

What `register_capability(capability_id, domain, name)` can bind out of the box: which ESPHome entity domains the library drives, and which Homey system capabilities each one reads and sets without a parser of your own.

The defaults live in [`src/homey_esphomedriver/system/`](src/homey_esphomedriver/system/), one module per domain.

## How a capability is looked up

1. The full capability id, then its base: `dim.led` uses `dim`, `measure_temperature.outside` uses `measure_temperature`.
2. If neither is listed, the domain's catch-all, when it has one (see [Any capability](#any-capability)). An entity that only reports gets no catch-all for a capability Homey lets the user set (see [Read-only entities](#read-only-entities)).
3. If nothing matches, `register_capability` raises `ValueError` unless you pass a `report_parser` or `set_parser`.

**Reads** means the entity's state is written to the capability. **Sets** means a change in Homey sends a `<domain>_command`.

## Domain-specific capabilities

### `alarm_control_panel`

| Capability | Reads | Sets | Mapping |
| --- | :---: | :---: | --- |
| `homealarm_state` | ✓ | ✓ | `disarmed` ↔ disarmed; `armed` ↔ armed away / vacation; `partially_armed` ↔ armed home / night / custom bypass. Setting picks the first arm command the panel supports. Pending, arming, disarming and triggered leave the capability as is. |

### `binary_sensor`

| Capability | Reads | Sets | Mapping |
| --- | :---: | :---: | --- |
| `alarm_connectivity` | ✓ | | Inverted: ESPHome *connected* → `false` |
| `battery_charging_state` | ✓ | | `on` → `charging`, `off` → `idle` |
| any other (`alarm_*`, `alarm_motion`, `alarm_contact`, …) | ✓ | | Boolean as is |

### `climate`

Temperatures are converted from the entity's `temperature_unit` to °C and back.

| Capability | Reads | Sets | Mapping |
| --- | :---: | :---: | --- |
| `onoff` | ✓ | ✓ | On when mode ≠ off. Turning on picks heat-cool, auto, heat or cool, the first the entity supports. |
| `thermostat_mode` | ✓ | ✓ | `heat`, `cool`, `auto` (heat-cool or auto), `off`, `dry`, `fan_only` |
| `measure_temperature` | ✓ | | Current temperature |
| `target_temperature` | ✓ | ✓ | Target temperature |
| `target_temperature_min` | ✓ | ✓ | Target temperature low (two-point) |
| `target_temperature_max` | ✓ | ✓ | Target temperature high (two-point) |
| `measure_humidity` | ✓ | | Current humidity |
| `target_humidity` | ✓ | ✓ | Target humidity |
| `fan_mode` | ✓ | ✓ | Built-in fan modes, lowercased (`low`, `auto`, …), or a custom fan mode by name. A mode the entity does not list is not reported. |
| `swing_mode` | ✓ | ✓ | `off`, `both`, `horizontal`, `vertical` |

### `cover`

Position and tilt are 0–1 on both sides; 0 is closed.

| Capability | Reads | Sets | Mapping |
| --- | :---: | :---: | --- |
| `windowcoverings_state` | ✓ | ✓ | `up` / `down` / `idle` from the current operation. Setting `up` opens, `down` closes, `idle` stops. |
| `windowcoverings_set` | ✓ | ✓ | Position |
| `windowcoverings_tilt_set` | ✓ | ✓ | Tilt |
| `windowcoverings_tilt_up` | | ✓ | Tilt to 1 |
| `windowcoverings_tilt_down` | | ✓ | Tilt to 0 |
| `garagedoor_closed` | ✓ | ✓ | Closed at position 0; only reported once the door stops moving |

### `fan`

| Capability | Reads | Sets | Mapping |
| --- | :---: | :---: | --- |
| `onoff` | ✓ | ✓ | Fan state |
| `fan_speed` | ✓ | ✓ | `speed_level / supported_speed_count`. Setting 0 turns the fan off. |
| `fan_mode` | ✓ | ✓ | Preset mode, lowercased in Homey and title-cased to ESPHome |

### `light`

| Capability | Reads | Sets | Mapping |
| --- | :---: | :---: | --- |
| `onoff` | ✓ | ✓ | Light state |
| `dim` | ✓ | ✓ | Brightness 0–1. Setting 0 turns the light off. |
| `light_mode` | ✓ | ✓ | `color` for RGB modes, `temperature` for color-temperature and cold/warm-white modes. Setting it re-sends the color or temperature the other capabilities hold. |
| `light_hue` | ✓ | ✓\* | From the RGB value via HSV |
| `light_saturation` | ✓ | ✓\* | From the RGB value via HSV |
| `light_temperature` | ✓ | ✓ | 0 (cool) to 1 (warm) across the light's mired range; 2000–6500 K if the light lists none |

\* `light_hue` and `light_saturation` are only settable when both are bound to the same light. They are then sent together in one command.

### `lock`

| Capability | Reads | Sets | Mapping |
| --- | :---: | :---: | --- |
| `locked` | ✓ | ✓ | Locked state; lock / unlock command |
| `alarm_door_fault` | ✓ | | `true` when the lock is jammed |

### `media_player`

| Capability | Reads | Sets | Mapping |
| --- | :---: | :---: | --- |
| `speaker_playing` | ✓ | ✓ | Playing or announcing. Setting `false` pauses if the player supports it, otherwise stops. |
| `speaker_stop` | | ✓ | Stop |
| `volume_set` | ✓ | ✓ | Volume 0–1 |
| `volume_mute` | ✓ | ✓ | Mute / unmute |
| `volume_up` | | ✓ | Volume up |
| `volume_down` | | ✓ | Volume down |

### `siren`

| Capability | Reads | Sets | Mapping |
| --- | :---: | :---: | --- |
| `onoff` | ✓ | ✓ | Siren state |
| `volume_set` | | ✓ | Volume; ESPHome does not report it back |

### `valve`

| Capability | Reads | Sets | Mapping |
| --- | :---: | :---: | --- |
| `onoff` | ✓ | ✓ | Open when position ≠ 0. Setting opens fully or closes. |
| `valve_position` | ✓ | ✓ | Position 0–1 |

### `water_heater`

Temperatures are converted from the entity's `temperature_unit` to °C and back.

| Capability | Reads | Sets | Mapping |
| --- | :---: | :---: | --- |
| `onoff` | ✓ | ✓ | On flag |
| `heater_operation_mode` | ✓ | ✓ | `off`, `eco`, `electric`, `performance`, `high_demand`, `heat_pump`, `gas` |
| `measure_temperature` | ✓ | | Current temperature |
| `target_temperature` | ✓ | ✓ | Target temperature |
| `target_temperature_min` | ✓ | ✓ | Target temperature low |
| `target_temperature_max` | ✓ | ✓ | Target temperature high |

## Any capability

These domains carry a single value, so they bind to any capability without a parser: your own, and Homey's, apart from the settable ones on a read-only entity.

| Domain | Reads | Sets | Value |
| --- | :---: | :---: | --- |
| `sensor` | ✓ | | Number, converted to the capability's unit (see below). Typically `measure_*` or `meter_*`. |
| `binary_sensor` | ✓ | | Boolean (apart from the ones above). Typically `alarm_*`. |
| `text_sensor` | ✓ | | String |
| `number` | ✓ | ✓ | Number |
| `select` | ✓ | ✓ | String (the option) |
| `switch` | ✓ | ✓ | Boolean. Typically `onoff`. |
| `text` | ✓ | ✓ | String |
| `button` | | ✓ | Any value presses it. Typically `button.*`. |
| `event` | ✓ | | The event type that fired. Usually better handled with `register_state_listener` and a Flow trigger. |

### Read-only entities

`sensor`, `binary_sensor`, `text_sensor` and `event` entities only report. Homey shows a settable capability as a toggle, slider, picker or button, and on an entity that takes no commands, using it would fail. So these domains have no default for the 63 settable Homey capabilities (`SETTABLE` in [`system/__init__.py`](src/homey_esphomedriver/system/__init__.py)), such as `onoff`, `locked`, `garagedoor_closed`, `windowcoverings_closed`, `dim`, `target_temperature` and `thermostat_mode`. `register_capability` raises instead.

Bind a capability that only shows a value, such as `alarm_contact` for a door or window sensor. To show a settable capability anyway, pass a `report_parser` and make it read-only in `driver.compose.json`:

```json
"capabilitiesOptions": {
  "garagedoor_closed": { "setable": false, "uiComponent": "sensor" }
}
```

The library cannot tell whether your own capabilities are settable, so it binds them either way.

### Sensor unit conversion

A `sensor` reading is converted from the entity's `unit_of_measurement` to the unit Homey expects for these capabilities (by base id, so `measure_power.l1` converts too). Any other capability gets the value as is.

| Group | Capabilities |
| --- | --- |
| Temperature | `measure_temperature`, `measure_dew_point` |
| Electricity | `measure_power`, `measure_apparent_power`, `measure_reactive_power`, `measure_current`, `measure_voltage`, `measure_battery_voltage`, `measure_frequency`, `meter_power`, `meter_reactive_energy` |
| Gas and water | `meter_gas`, `meter_water`, `measure_water`, `measure_content_volume` |
| Weather | `measure_pressure`, `measure_rain`, `measure_rain_intensity`, `measure_wind_strength`, `measure_gust_strength`, `measure_irradiance` |
| Air quality | `measure_co`, `measure_o3`, `measure_so2`, `measure_absolute_humidity` |
| Physical | `measure_distance`, `measure_area`, `measure_weight`, `measure_speed`, `measure_duration`, `measure_energy_distance` |
| Data | `measure_data_rate`, `measure_data_size` |
| Other | `measure_conductivity`, `measure_blood_glucose` |

## Not supported

### ESPHome domains

`register_capability` rejects these domains, even with a parser:

| Domain | What it is |
| --- | --- |
| `camera` | Camera snapshots / stream |
| `date`, `time`, `datetime` | Date and time inputs |
| `update` | Firmware update entity |
| `infrared` | IR transmitter / receiver |
| `radio_frequency` | RF transmitter / receiver |

### Parts of supported domains without a default

Bind these with your own `report_parser` / `set_parser`, `register_state_listener`, or a command through `self.client.command(...)`.

| Domain | Not mapped |
| --- | --- |
| `alarm_control_panel` | Pending, arming, disarming and triggered states (a triggered alarm sets no `alarm_*` capability); arm and disarm codes are not sent, so a panel that requires a code rejects the command |
| `climate` | Presets (home, away, boost, eco, sleep, …) and custom presets; current action (heating, cooling, idle, drying, defrosting) |
| `cover` | `windowcoverings_closed` |
| `fan` | Oscillation and direction |
| `light` | Effects; white, cold-white and warm-white channel levels; color brightness separate from brightness; transitions and flash. `light_mode` stays unchanged in on/off, brightness-only and white modes. |
| `lock` | The open (unlatch) command. Locking and unlocking read as not locked. |
| `media_player` | Playing a URL or an announcement; repeat, enqueue and clear playlist; turn on / off; media info (title, artist, artwork) |
| `siren` | Tones and duration; the volume is not reported back |
| `valve` | Stop and the opening / closing state |
| `water_heater` | Away mode |
| `event` | No Homey capability fits; use `register_state_listener` and a Flow trigger |

### On the Homey side

- **Capability options are not filled in from the entity.** Min, max and step of a `number` or climate setpoint, the options of a `select`, the fan or preset modes and the thermostat modes are not copied to `capabilitiesOptions`. Set them in `driver.compose.json` or in `on_pair_device`.
- **The `duration` option is ignored.** The default parsers send no transition, so dimming over time from a Flow card is instant. A `set_parser` gets the options as `opts` and can pass `transition_length` itself.
- **Unknown capabilities on multi-value domains.** `light`, `climate`, `cover`, `fan`, `lock`, `media_player`, `siren`, `valve`, `water_heater` and `alarm_control_panel` only know the capabilities listed above. Anything else needs a parser.

### ESPHome API features beyond entities

None of these have built-in support. The ones the API client exposes can be called from your own code through `self.client.command("<APIClient method>", ...)`.

- User-defined actions (services) in the YAML (`api: actions:`)
- Home Assistant actions and state imports the node asks for (`homeassistant.action`, `homeassistant` sensors)
- Voice assistant
- Bluetooth proxy
- Device logs

## Custom parsers

Any domain above also accepts a `report_parser` and/or `set_parser`, which override the defaults. That is how you bind your own capability to a multi-value domain such as `light` or `climate`. See [Parsers](README.md#parsers) in the README.
