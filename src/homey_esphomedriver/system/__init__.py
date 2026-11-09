"""System capabilities: default parsers per Homey capability and ESPHome domain.

One module per ESPHome domain, each with a ``CAPABILITIES`` table, an
optional ``default(capability_id)`` for any other capability on a
single-value domain, and optional ``MULTI`` groups that are set together in
one command. A domain whose entities only report sets ``REPORTS_ONLY``; its
default then leaves out the capabilities in :data:`SETTABLE`.

Parsers are kept per domain because the same Homey capability reads
differently from each: ``onoff`` is a light's state but a valve's
position.

A ``report_parser(state, entity)`` turns an ESPHome state into the capability
value; ``None`` leaves the capability as is. A
``set_parser(value, opts, entity)`` returns the keyword arguments for the
domain's ``<domain>_command``; ``None`` sends nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import ModuleType
from typing import TYPE_CHECKING, Any

from aioesphomeapi import (
    AlarmControlPanelInfo,
    BinarySensorInfo,
    ButtonInfo,
    ClimateInfo,
    CoverInfo,
    EntityInfo,
    EventInfo,
    FanInfo,
    LightInfo,
    LockInfo,
    MediaPlayerInfo,
    NumberInfo,
    SelectInfo,
    SensorInfo,
    SirenInfo,
    SwitchInfo,
    TextInfo,
    TextSensorInfo,
    ValveInfo,
    WaterHeaterInfo,
)

if TYPE_CHECKING:
    from homey_esphomedriver.esphome_device import EspHomeDevice


@dataclass(frozen=True, slots=True, eq=False)
class BoundEntity:
    """The ESPHome entity a capability is bound to on the current connection.

    Passed to every parser. :attr:`info` carries what the entity supports,
    such as its unit, color temperature range or speed count, so parsers need
    nothing stored at pair time.
    """

    device: EspHomeDevice
    """Homey device the entity belongs to."""

    info: EntityInfo
    """Entity description listed on this connection."""

    domain: str
    """ESPHome domain, such as ``light``; set with ``<domain>_command``."""

    capabilities: Sequence[str] = field(default=())
    """Capability ids bound to this entity, in registration order."""

    @property
    def key(self) -> int:
        """Entity key on this connection."""
        return self.info.key

    @property
    def name(self) -> str:
        """Entity name the YAML author chose."""
        return self.info.name

    def capability_value(self, base: str) -> Any:
        """Current value of the capability with this base bound to the entity.

        Lets a parser read a sibling, such as the saturation while setting the
        hue. ``None`` when no such capability is bound.
        """
        for capability_id in self.capabilities:
            if capability_base(capability_id) == base:
                return self.device.get_capability_value(capability_id)
        return None


ReportParser = Callable[[Any, BoundEntity], Any]
"""``(state, entity)`` to a capability value, or ``None`` to skip the write."""

SetParser = Callable[[Any, Mapping[str, Any], BoundEntity], Mapping[str, Any] | None]
"""``(value, opts, entity)`` to ``<domain>_command`` kwargs, or ``None``."""

MultiSetParser = Callable[
    [Mapping[str, Any], Mapping[str, Any], BoundEntity], Mapping[str, Any] | None
]
"""``(values by capability base, opts, entity)`` to command kwargs, or ``None``."""


@dataclass(frozen=True, slots=True)
class SystemCapability:
    """Default parsers for one capability on one domain."""

    report_parser: ReportParser | None = None
    set_parser: SetParser | None = None


@dataclass(frozen=True, slots=True)
class MultiCapability:
    """Capabilities set together in one command, such as hue and saturation.

    Registered once every base in :attr:`capabilities` is bound to the same
    entity, through Homey's debounced multiple-capability listener.
    """

    capabilities: tuple[str, ...]
    """Capability bases in the group, such as ``light_hue`` and ``light_saturation``."""

    set_parser: MultiSetParser


SETTABLE: frozenset[str] = frozenset(
    {
        "audio_output",
        "button",
        "channel_down",
        "channel_up",
        "cooking_time",
        "dim",
        "evcharger_charging",
        "fan_mode",
        "fan_speed",
        "garagedoor_closed",
        "heater_operation_mode",
        "homealarm_state",
        "hot_water_mode",
        "laundry_dryer_dryness",
        "laundry_washer_cycles",
        "laundry_washer_speed",
        "light_hue",
        "light_mode",
        "light_saturation",
        "light_temperature",
        "lock_mode",
        "locked",
        "media_input",
        "microwave_mode",
        "mower_state",
        "onoff",
        "oscillating",
        "oven_mode",
        "power_boost",
        "power_level",
        "pump_mode",
        "pump_setpoint",
        "refrigerator_mode",
        "speaker_next",
        "speaker_playing",
        "speaker_prev",
        "speaker_repeat",
        "speaker_shuffle",
        "speaker_stop",
        "swing_mode",
        "target_humidity",
        "target_humidity_max",
        "target_humidity_min",
        "target_power",
        "target_power_mode",
        "target_temperature",
        "target_temperature_level",
        "target_temperature_max",
        "target_temperature_min",
        "thermostat_mode",
        "vacuumcleaner_job_mode",
        "vacuumcleaner_state",
        "valve_position",
        "volume_down",
        "volume_mute",
        "volume_set",
        "volume_up",
        "windowcoverings_closed",
        "windowcoverings_set",
        "windowcoverings_state",
        "windowcoverings_tilt_down",
        "windowcoverings_tilt_set",
        "windowcoverings_tilt_up",
    }
)
"""Homey system capabilities a user can set, as of homey-lib 2.53.0.

Homey shows them as a toggle, slider, picker or button. An entity that only
reports cannot act on them, so tapping one would fail.
"""


def capability_base(capability_id: str) -> str:
    """Homey capability type, without a ``.suffix``: ``dim.led`` is ``dim``."""
    return capability_id.split(".", 1)[0]


# Imported here, below the types the domain modules import from this package.
from homey_esphomedriver.system import (  # noqa: E402
    alarm_control_panel,
    binary_sensor,
    button,
    climate,
    cover,
    event,
    fan,
    light,
    lock,
    media_player,
    number,
    select,
    sensor,
    siren,
    switch,
    text,
    text_sensor,
    valve,
    water_heater,
)

DOMAINS: Mapping[str, tuple[type[EntityInfo], ModuleType]] = {
    "alarm_control_panel": (AlarmControlPanelInfo, alarm_control_panel),
    "binary_sensor": (BinarySensorInfo, binary_sensor),
    "button": (ButtonInfo, button),
    "climate": (ClimateInfo, climate),
    "cover": (CoverInfo, cover),
    "event": (EventInfo, event),
    "fan": (FanInfo, fan),
    "light": (LightInfo, light),
    "lock": (LockInfo, lock),
    "media_player": (MediaPlayerInfo, media_player),
    "number": (NumberInfo, number),
    "select": (SelectInfo, select),
    "sensor": (SensorInfo, sensor),
    "siren": (SirenInfo, siren),
    "switch": (SwitchInfo, switch),
    "text": (TextInfo, text),
    "text_sensor": (TextSensorInfo, text_sensor),
    "valve": (ValveInfo, valve),
    "water_heater": (WaterHeaterInfo, water_heater),
}
"""Domain name to its entity info type and its system capability module."""


def domain_of(info: EntityInfo) -> str | None:
    """Domain name of an entity, or ``None`` for a domain Homey does not drive."""
    for domain, (info_type, _module) in DOMAINS.items():
        if type(info) is info_type:
            return domain
    return None


def reports_only(domain: str) -> bool:
    """Whether entities of ``domain`` only report and take no commands."""
    entry = DOMAINS.get(domain)
    return bool(entry is not None and getattr(entry[1], "REPORTS_ONLY", False))


def lookup(capability_id: str, domain: str) -> SystemCapability | None:
    """Default parsers for ``capability_id`` on ``domain``.

    Tries the full id, then its base, so ``dim.led`` finds ``dim``, then the
    domain's ``default`` for any capability. A domain that only reports has
    no default for a capability in :data:`SETTABLE`.
    """
    entry = DOMAINS.get(domain)
    if entry is None:
        return None
    module = entry[1]
    capabilities: Mapping[str, SystemCapability] = module.CAPABILITIES
    found = capabilities.get(capability_id) or capabilities.get(
        capability_base(capability_id)
    )
    if found is not None:
        return found
    if reports_only(domain) and capability_base(capability_id) in SETTABLE:
        return None
    default: Callable[[str], SystemCapability] | None = getattr(module, "default", None)
    return default(capability_id) if default is not None else None


def multi_capabilities(domain: str) -> Sequence[MultiCapability]:
    """Groups of capabilities ``domain`` sets together in one command."""
    entry = DOMAINS.get(domain)
    if entry is None:
        return ()
    groups: Sequence[MultiCapability] = getattr(entry[1], "MULTI", ())
    return groups
