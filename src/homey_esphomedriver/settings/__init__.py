"""Write settings-page fields to the ESPHome entities backing them.

The entity is written only when the user saves the setting. A deep-sleep node
that is asleep at that moment gets the write when it next wakes, as Z-Wave
does for battery nodes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from homey_esphomedriver.entities.commands.generic import (
    WRITABLE_DOMAINS,
    write_entity_value,
)
from homey_esphomedriver.settings.links import bind_setting_entities

if TYPE_CHECKING:
    from homey_esphomedriver.esphome_client import EspHomeClient
    from homey_esphomedriver.esphome_device import EspHomeDevice

BINDINGS_STORE_KEY = "setting_entities"
PENDING_STORE_KEY = "pending_settings"


class SettingEntitySync:
    """Write and queue settings linked to an entity for one device."""

    def __init__(self, device: EspHomeDevice) -> None:
        self._device = device
        self._bound: dict[str, dict[str, Any]] = {}
        self._resolved: frozenset[str] = frozenset()
        self._pending: dict[str, Any] = {}
        store = device.get_store()
        self._load_bindings(store.get(BINDINGS_STORE_KEY))
        pending = store.get(PENDING_STORE_KEY)
        if isinstance(pending, Mapping):
            self._pending = {
                setting_id: value
                for setting_id, value in pending.items()
                if setting_id in self._bound
            }

    @property
    def _linked(self) -> Mapping[str, Any]:
        return self._device.brand_profile.setting_entities

    def _load_bindings(self, bindings: object) -> None:
        """Index bindings for settings the driver still links.

        A ``None`` binding is a link already checked against the node's
        entities and left unbound; it counts as resolved, not bound.
        """
        linked = self._linked
        self._bound = {}
        resolved: set[str] = set()
        if isinstance(bindings, Mapping):
            for setting_id, binding in bindings.items():
                if setting_id not in linked:
                    continue
                if binding is None:
                    resolved.add(setting_id)
                elif isinstance(binding, Mapping):
                    resolved.add(setting_id)
                    self._bound[setting_id] = {
                        "key": int(binding["key"]),
                        "domain": str(binding["domain"]),
                    }
        self._resolved = frozenset(resolved)

    # --- bindings -----------------------------------------------------------

    async def update_bindings(self, bindings: Mapping[str, Any] | None) -> None:
        """Store bindings from a fresh entity listing.

        Args:
            bindings: ``store.setting_entities`` from a mapper scratch.
        """
        if not self._linked:
            return
        fresh = dict(bindings or {})
        if fresh != self._device.get_store().get(BINDINGS_STORE_KEY):
            await self._device.set_store_value(BINDINGS_STORE_KEY, fresh)
        self._load_bindings(fresh)

    async def ensure_bindings(self, client: EspHomeClient) -> None:
        """Bind settings a driver update linked after this device was paired.

        Lists entities only for links not yet checked against this node. The
        outcome is stored, unbound links included, so a link whose entity the
        node lacks is not looked up on every wake; Refresh and a firmware
        rebuild check it again. A listing that fails resolves nothing, so the
        next session tries again.
        """
        linked = self._linked
        if set(linked) <= self._resolved:
            return
        entities, _services = await client.list_entities_services()
        await self.update_bindings(bind_setting_entities(entities, linked))

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
            if setting_id in self._bound and new_settings.get(setting_id) is not None
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
                    binding = self._bound[setting_id]
                    write_entity_value(client, binding["domain"], binding["key"], value)
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
        """Convert a setting value to what its entity's command takes."""
        coerce = WRITABLE_DOMAINS[self._bound[setting_id]["domain"]].coerce
        try:
            return coerce(self._device.setting_to_entity(setting_id, value))
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
            binding = self._bound.get(setting_id)
            if binding is not None:
                try:
                    write_entity_value(
                        client,
                        binding["domain"],
                        binding["key"],
                        self._entity_value(setting_id, value),
                    )
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
