"""Write settings-page fields to the ESPHome entities backing them.

The entity is written when the user saves the setting. A deep-sleep node that
is asleep at that moment gets the write when it next wakes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from homey_esphomedriver.settings.links import DOMAIN_COERCE, SettingEntity

if TYPE_CHECKING:
    from homey_esphomedriver.esphome_client import EspHomeClient
    from homey_esphomedriver.esphome_device import EspHomeDevice
    from homey_esphomedriver.system import BoundEntity

PENDING_STORE_KEY = "pending_settings"


class SettingEntitySync:
    """Write and queue settings linked to an entity for one device."""

    def __init__(self, device: EspHomeDevice) -> None:
        self._device = device
        self._pending: dict[str, Any] = {}
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


def _write(client: EspHomeClient, entity: BoundEntity, value: Any) -> None:
    """Send a converted setting value to its entity."""
    extra = {"device_id": entity.info.device_id} if entity.info.device_id else {}
    client.command(f"{entity.domain}_command", entity.key, value, **extra)
