"""Runtime dispatch of ESPHome entity states onto Homey capabilities.

Builds a key-to-capabilities index from pair-time options, then routes each
:class:`~aioesphomeapi.EntityState` to the matching handler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aioesphomeapi import (
    AlarmControlPanelEntityState,
    BinarySensorState,
    ClimateState,
    CoverState,
    EntityState,
    Event,
    FanState,
    LightState,
    LockEntityState,
    MediaPlayerEntityState,
    NumberState,
    SelectState,
    SensorState,
    SirenState,
    SwitchState,
    TextSensorState,
    ValveState,
    WaterHeaterState,
)

from homey_esphomedriver.entities.state.alarm_control_panel import (
    AlarmControlPanelEntityStateUpdateHandler,
)
from homey_esphomedriver.entities.state.base import AbstractEntityStateUpdateHandler
from homey_esphomedriver.entities.state.binary_sensor import (
    BinarySensorEntityStateUpdateHandler,
)
from homey_esphomedriver.entities.state.climate import (
    ClimateEntityStateUpdateHandler,
)
from homey_esphomedriver.entities.state.cover import (
    CoverEntityStateUpdateHandler,
)
from homey_esphomedriver.entities.state.event import (
    EventEntityStateUpdateHandler,
)
from homey_esphomedriver.entities.state.fan import (
    FanEntityStateUpdateHandler,
)
from homey_esphomedriver.entities.state.light import (
    LightEntityStateUpdateHandler,
)
from homey_esphomedriver.entities.state.lock import (
    LockEntityStateUpdateHandler,
)
from homey_esphomedriver.entities.state.media_player import (
    MediaPlayerEntityStateUpdateHandler,
)
from homey_esphomedriver.entities.state.number import (
    NumberEntityStateUpdateHandler,
)
from homey_esphomedriver.entities.state.select import (
    SelectEntityStateUpdateHandler,
)
from homey_esphomedriver.entities.state.sensor import (
    SensorEntityStateUpdateHandler,
)
from homey_esphomedriver.entities.state.siren import (
    SirenEntityStateUpdateHandler,
)
from homey_esphomedriver.entities.state.switch import (
    SwitchEntityStateUpdateHandler,
)
from homey_esphomedriver.entities.state.text_sensor import (
    TextSensorEntityStateUpdateHandler,
)
from homey_esphomedriver.entities.state.valve import (
    ValveEntityStateUpdateHandler,
)
from homey_esphomedriver.entities.state.water_heater import (
    WaterHeaterEntityStateUpdateHandler,
)
from homey_esphomedriver.esphome_util import debug_log

if TYPE_CHECKING:
    from homey.device import Device


class DeviceEntityStateHandler:
    """Owns the key→capability index and dispatches subscribed states."""

    def __init__(self, device: Device) -> None:
        self._device = device
        self._key_to_capabilities: dict[int, list[str]] = {}
        self._last_states: dict[int, EntityState] = {}
        self._handlers_by_type: dict[
            type[EntityState], AbstractEntityStateUpdateHandler
        ] = {
            AlarmControlPanelEntityState: AlarmControlPanelEntityStateUpdateHandler(
                device
            ),
            BinarySensorState: BinarySensorEntityStateUpdateHandler(device),
            ClimateState: ClimateEntityStateUpdateHandler(device),
            CoverState: CoverEntityStateUpdateHandler(device),
            Event: EventEntityStateUpdateHandler(device),
            FanState: FanEntityStateUpdateHandler(device),
            LightState: LightEntityStateUpdateHandler(device),
            LockEntityState: LockEntityStateUpdateHandler(device),
            MediaPlayerEntityState: MediaPlayerEntityStateUpdateHandler(device),
            NumberState: NumberEntityStateUpdateHandler(device),
            SelectState: SelectEntityStateUpdateHandler(device),
            SensorState: SensorEntityStateUpdateHandler(device),
            SirenState: SirenEntityStateUpdateHandler(device),
            SwitchState: SwitchEntityStateUpdateHandler(device),
            TextSensorState: TextSensorEntityStateUpdateHandler(device),
            ValveState: ValveEntityStateUpdateHandler(device),
            WaterHeaterState: WaterHeaterEntityStateUpdateHandler(device),
        }

    async def init(self) -> None:
        """Build the entity-key index and apply cached states for newly mapped keys."""
        self._key_to_capabilities.clear()

        for capability in self._device.get_capabilities():
            if (
                capability.startswith(
                    ("alarm_doorbell.", "event_button.", "event_generic.")
                )
                and self._device.get_capability_value(capability) is None
            ):
                # Homey shows these as null until a value is written.
                await self._device.set_capability_value(
                    capability,
                    False if capability.startswith("alarm_doorbell.") else "idle",
                )
            # WORKAROUND: get_capability_options raises on stored null
            # (Athom will return {}).
            key = (self._device._capabilities_options.get(capability) or {}).get("key")
            if key is None:
                continue
            self._key_to_capabilities.setdefault(int(key), []).append(capability)

        for state in list(self._last_states.values()):
            await self._apply_state(state)

    def uninit(self) -> None:
        """Release per-handler timers and other resources."""
        self._last_states.clear()
        for handler in self._handlers_by_type.values():
            handler.uninit()

    async def handle_state(self, state: EntityState) -> None:
        """Route one ESPHome state update to the matching Homey capabilities."""
        await self._apply_state(state)

    async def _apply_state(self, state: EntityState) -> None:
        capabilities = self._key_to_capabilities.get(state.key, [])
        if not capabilities:
            if type(state) in self._handlers_by_type:
                self._last_states[state.key] = state
            return
        self._last_states.pop(state.key, None)
        self._debug(
            f"Handling entity state key={state.key} caps={capabilities}: {state}"
        )
        handler = self._handlers_by_type.get(type(state))
        if handler is None:
            return
        await handler.handle(state, capabilities)

    def _debug(self, *args: object) -> None:
        debug_log(self._device.log, *args)
