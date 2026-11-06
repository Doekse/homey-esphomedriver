"""Keep settings-page fields in step with the ESPHome entities backing them.

The node holds the value, so it is the truth for what the value currently is:
reported states are mirrored into the Homey setting, including changes made
from Home Assistant or the ESPHome web server. The entity is written only when
the user saves the setting. A deep-sleep node that is asleep at that moment
gets the write when it next wakes, as Z-Wave does for battery nodes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from aioesphomeapi import EntityState

from homey_esphomedriver.entities.commands.generic import (
    WRITABLE_DOMAINS,
    write_entity_value,
)
from homey_esphomedriver.esphome_util import is_missing_number
from homey_esphomedriver.settings.links import bind_setting_entities, setting_matches

if TYPE_CHECKING:
    from homey_esphomedriver.esphome_client import EspHomeClient
    from homey_esphomedriver.esphome_device import EspHomeDevice

BINDINGS_STORE_KEY = "setting_entities"
PENDING_STORE_KEY = "pending_settings"

_WRITABLE_STATES = tuple(writable.state for writable in WRITABLE_DOMAINS.values())
"""States of the entity domains a setting can be backed by."""


class SettingEntitySync:
    """Write, mirror and queue settings linked to an entity for one device."""

    def __init__(self, device: EspHomeDevice) -> None:
        self._device = device
        self._converters: dict[
            str, tuple[Callable[[Any], Any] | None, Callable[[Any], Any] | None]
        ] = {}
        self._bound: dict[str, dict[str, Any]] = {}
        self._resolved: frozenset[str] = frozenset()
        self._by_key: dict[int, str] = {}
        self._pending: dict[str, Any] = {}
        self._latest: dict[int, EntityState] = {}
        self._mirror_queue: dict[str, Any] = {}
        self._mirror_task: asyncio.Task[None] | None = None
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
        self._by_key = {
            binding["key"]: setting_id for setting_id, binding in self._bound.items()
        }

    def uninit(self) -> None:
        """Stop a mirror still waiting on Homey."""
        task = self._mirror_task
        if task is not None and not task.done():
            task.cancel()
        self._mirror_task = None
        self._mirror_queue.clear()
        self._latest.clear()

    # --- bindings -----------------------------------------------------------

    async def update_bindings(self, bindings: Mapping[str, Any] | None) -> None:
        """Store bindings from a fresh entity listing and mirror cached states.

        Args:
            bindings: ``store.setting_entities`` from a mapper scratch.
        """
        if not self._linked:
            return
        fresh = dict(bindings or {})
        if fresh != self._device.get_store().get(BINDINGS_STORE_KEY):
            await self._device.set_store_value(BINDINGS_STORE_KEY, fresh)
        self._load_bindings(fresh)
        self._replay_cached_states()

    def _replay_cached_states(self) -> None:
        """Mirror the latest state of every bound entity.

        The connect dump may have gone by, and a number never repeats it.
        """
        for key in self._by_key:
            state = self._latest.get(key)
            if state is not None:
                self.on_state(state)

    # --- converters ---------------------------------------------------------

    def register(
        self,
        setting_id: str,
        *,
        to_entity: Callable[[Any], Any] | None = None,
        to_setting: Callable[[Any], Any] | None = None,
    ) -> None:
        """Set the value converters for one linked setting.

        Raises:
            ValueError: If ``setting_id`` is not linked to an entity, so a typo
                fails on init rather than silently passing values through.
        """
        if setting_id not in self._linked:
            raise ValueError(
                f"Setting {setting_id!r} is not linked to an entity; add "
                '"esphome": {"entity": "<object_id>"} to it in the manifest'
            )
        self._converters[setting_id] = (to_entity, to_setting)

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
        """Convert a setting value to what its entity's command takes.

        Raises:
            ValueError: For any failure of the brand's ``to_entity`` converter
                or the domain coercion, so a ``KeyError`` from a lookup table
                is handled the same as a value the entity cannot take.
        """
        coerce = WRITABLE_DOMAINS[self._bound[setting_id]["domain"]].coerce
        try:
            to_entity, _to_setting = self._converters.get(setting_id, (None, None))
            return coerce(value if to_entity is None else to_entity(value))
        except Exception as err:
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

    # --- node -> Homey ------------------------------------------------------

    def on_state(self, state: EntityState) -> None:
        """Mirror a reported value into its setting.

        Runs inline in the Native API read callback, so it only queues; the
        Homey write happens in a task. Every writable entity's latest state is
        kept, bound or not and whether or not a capability also takes it, so
        a setting bound later starts from the value the node reported.
        """
        if isinstance(state, _WRITABLE_STATES):
            self._latest[state.key] = state
        setting_id = self._by_key.get(state.key)
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
        try:
            _to_entity, to_setting = self._converters.get(setting_id, (None, None))
            value = reported if to_setting is None else to_setting(reported)
        except Exception as err:
            device.error(f"Could not convert {setting_id!r} from the node:", err)
            return
        if setting_matches(device.get_setting(setting_id), value):
            self._mirror_queue.pop(setting_id, None)
            return
        self._mirror_queue[setting_id] = value
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
