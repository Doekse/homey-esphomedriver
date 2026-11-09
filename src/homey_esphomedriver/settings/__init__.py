"""Keep settings-page fields in step with the ESPHome entities backing them.

The node holds the value, so it is the truth for what the value currently is:
reported states are mirrored into the Homey setting, including changes made
from Home Assistant or the ESPHome web server. The entity is written only when
the user saves the setting. A deep-sleep node that is asleep at that moment
gets the write when it next wakes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from aioesphomeapi import EntityState

from homey_esphomedriver.esphome_util import is_missing_number
from homey_esphomedriver.settings.links import (
    DOMAIN_COERCE,
    SettingEntity,
    setting_matches,
)

if TYPE_CHECKING:
    from homey_esphomedriver.esphome_client import EspHomeClient
    from homey_esphomedriver.esphome_device import EspHomeDevice
    from homey_esphomedriver.system import BoundEntity

PENDING_STORE_KEY = "pending_settings"


class SettingEntitySync:
    """Write, mirror and queue settings linked to an entity for one device."""

    def __init__(self, device: EspHomeDevice) -> None:
        self._device = device
        self._by_ref = {
            target.ref: setting_id for setting_id, target in self._linked.items()
        }
        self._pending: dict[str, Any] = {}
        self._mirror_queue: dict[str, Any] = {}
        self._mirror_task: asyncio.Task[None] | None = None
        pending = device.get_store().get(PENDING_STORE_KEY)
        if isinstance(pending, Mapping):
            self._pending = {
                setting_id: value
                for setting_id, value in pending.items()
                if setting_id in self._linked
            }

    @property
    def _linked(self) -> Mapping[str, SettingEntity]:
        return self._device.brand_profile.setting_entities

    def uninit(self) -> None:
        """Stop a mirror still waiting on Homey."""
        task = self._mirror_task
        if task is not None and not task.done():
            task.cancel()
        self._mirror_task = None
        self._mirror_queue.clear()

    def _entity(self, setting_id: str) -> BoundEntity | None:
        """The entity backing a setting on the current connection."""
        return self._device._bindings.entity(*self._linked[setting_id].ref)

    # --- Homey -> node ------------------------------------------------------

    async def on_settings(
        self,
        new_settings: Mapping[str, Any],
        changed_keys: tuple[str, ...],
    ) -> str | None:
        """Write saved settings to their entities.

        Returns:
            A save message when the writes wait for a sleeping node to wake.

        Raises:
            ValueError: A value the entity cannot take; Homey keeps the old one.
            RuntimeError: The node is offline and not a deep-sleep node.
        """
        changed = {
            setting_id: new_settings.get(setting_id)
            for setting_id in changed_keys
            if setting_id in self._linked and new_settings.get(setting_id) is not None
        }
        if not changed:
            return None
        # Check every value first, so an invalid one rejects the whole save
        # before anything reaches the node.
        values = {
            setting_id: self._entity_value(setting_id, value)
            for setting_id, value in changed.items()
        }

        device = self._device
        client = device.client
        if client is not None and client.available:
            try:
                for setting_id, value in values.items():
                    entity = self._entity(setting_id)
                    if entity is None:
                        device.log(
                            f"Setting {setting_id!r} has no entity on this node; "
                            "saved in Homey only"
                        )
                        continue
                    _write(client, entity, value)
            except Exception as err:
                if not self._sleeps(client):
                    raise RuntimeError(
                        device.homey.translate("errors.device_not_connected")
                    ) from err
            else:
                await self._drop_pending(changed)
                return None

        if not self._sleeps(client):
            raise RuntimeError(device.homey.translate("errors.device_not_connected"))
        self._pending.update(changed)
        await device.set_store_value(PENDING_STORE_KEY, dict(self._pending))
        device.log(f"Node asleep; {', '.join(changed)} will be written when it wakes")
        return device.homey.translate("settings.applied_on_wake")

    def _entity_value(self, setting_id: str, value: Any) -> Any:
        """Convert a setting value to what its entity's command takes.

        Raises:
            ValueError: A value the entity's command cannot take.
        """
        coerce = DOMAIN_COERCE[self._linked[setting_id].domain]
        try:
            return coerce(value)
        except (TypeError, ValueError) as err:
            raise ValueError(
                self._device.homey.translate("errors.setting_invalid")
            ) from err

    def _sleeps(self, client: EspHomeClient | None) -> bool:
        if client is not None:
            return client.deep_sleep
        return self._device.get_setting("deep_sleep") == "Yes"

    async def flush_pending(self) -> None:
        """Write settings saved while the node slept; it is awake now."""
        if not self._pending:
            return
        device = self._device
        client = device.client
        if client is None or not client.available:
            return
        written: dict[str, Any] = {}
        for setting_id, value in list(self._pending.items()):
            entity = self._entity(setting_id)
            if entity is None:
                device.error(f"Dropped queued setting {setting_id!r}: no entity")
            else:
                try:
                    _write(client, entity, self._entity_value(setting_id, value))
                except ValueError as err:
                    device.error(f"Dropped queued setting {setting_id!r}:", err)
                except Exception as err:
                    # The node went back to sleep; keep the rest for next time.
                    device.error(f"Could not write queued setting {setting_id!r}:", err)
                    break
            written[setting_id] = value
        await self._drop_pending(written)

    async def _drop_pending(self, setting_ids: Mapping[str, Any]) -> None:
        if not any(setting_id in self._pending for setting_id in setting_ids):
            return
        for setting_id in setting_ids:
            self._pending.pop(setting_id, None)
        await self._device.set_store_value(PENDING_STORE_KEY, dict(self._pending))

    # --- node -> Homey ------------------------------------------------------

    def on_state(self, state: EntityState) -> None:
        """Mirror a reported value into its setting.

        Runs inline in the Native API read callback, so it only queues; the
        Homey write happens in a task.
        """
        ref = self._device._bindings.ref_for(state)
        setting_id = self._by_ref.get(ref) if ref is not None else None
        if setting_id is None or setting_id in self._pending:
            # A queued edit wins over the value the node still holds.
            return
        if getattr(state, "missing_state", False):
            return
        reported = getattr(state, "state", None)
        if reported is None or (
            isinstance(reported, float) and is_missing_number(reported)
        ):
            return
        device = self._device
        if setting_matches(device.get_setting(setting_id), reported):
            self._mirror_queue.pop(setting_id, None)
            return
        self._mirror_queue[setting_id] = reported
        if self._mirror_task is None or self._mirror_task.done():
            self._mirror_task = asyncio.create_task(self._run_mirror())

    async def _run_mirror(self) -> None:
        """Write queued values into their settings, newest value per setting."""
        device = self._device
        while self._mirror_queue:
            setting_id = next(iter(self._mirror_queue))
            value = self._mirror_queue.pop(setting_id)
            if setting_matches(device.get_setting(setting_id), value):
                continue
            try:
                await device.set_settings({setting_id: value})
            except Exception as err:
                # Refused while a save is in progress, and that save wins: a
                # node reports nothing for a value it rejects, so a report then
                # is the echo of the value being saved. Otherwise Homey rejects
                # the value itself, such as one outside the setting's range.
                device.log(f"Did not mirror {setting_id!r} into settings:", err)


def _write(client: EspHomeClient, entity: BoundEntity, value: Any) -> None:
    """Send a converted setting value to its entity."""
    extra = {"device_id": entity.info.device_id} if entity.info.device_id else {}
    client.command(f"{entity.domain}_command", entity.key, value, **extra)
