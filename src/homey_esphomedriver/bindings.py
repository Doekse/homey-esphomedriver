"""Capabilities and state listeners bound to ESPHome entities.

The registry behind :meth:`EspHomeDevice.register_capability` and
:meth:`EspHomeDevice.register_state_listener`. Bindings are made in
``on_esphome_init`` and kept in memory only: the app makes them again on
every start, so nothing in the store can go stale. Each connection lists the
node's entities before it subscribes to states, and every binding is resolved
by entity domain, name and sub-device then, because entity keys can change
with the firmware.
"""

from __future__ import annotations

import asyncio
import inspect
import math
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from aioesphomeapi import EntityInfo, EntityState

from homey_esphomedriver.system import (
    DOMAINS,
    SETTABLE,
    BoundEntity,
    MultiCapability,
    ReportParser,
    SetParser,
    capability_base,
    domain_of,
    lookup,
    multi_capabilities,
    reports_only,
)

if TYPE_CHECKING:
    from homey_esphomedriver.esphome_device import EspHomeDevice

EntityRef = tuple[str, str, int]
"""``(domain, name, device_id)``: an entity as the app names it."""

StateListener = Callable[[EntityState, BoundEntity], Awaitable[None] | None]
"""Called with every state of an entity, after its capabilities are written."""


@dataclass(frozen=True, slots=True)
class _Binding:
    capability_id: str
    entity: EntityRef
    report_parser: ReportParser | None
    set_parser: SetParser | None
    custom_set: bool
    """Whether the app passed its own ``set_parser``, which keeps it out of MULTI."""


class CapabilityBindings:
    """Bindings of one device and the entities of its current connection."""

    def __init__(self, device: EspHomeDevice) -> None:
        self._device = device
        self._bindings: dict[str, _Binding] = {}
        self._groups: dict[EntityRef, list[str]] = {}
        self._listeners: dict[EntityRef, list[StateListener]] = {}
        self._infos: dict[EntityRef, EntityInfo] = {}
        self._by_key: dict[tuple[int, int], EntityRef] = {}
        self._last_states: dict[EntityRef, EntityState] = {}
        self._listed = False

    # --- registration -------------------------------------------------------

    def register_capability(
        self,
        capability_id: str,
        domain: str,
        name: str,
        *,
        device_id: int = 0,
        set_parser: SetParser | None = None,
        report_parser: ReportParser | None = None,
    ) -> None:
        """Bind a capability the device has to an entity.

        Raises:
            ValueError: The device lacks the capability, the domain is unknown,
                or neither the app nor the system capabilities give a parser.
        """
        device = self._device
        if not device.has_capability(capability_id):
            raise ValueError(
                f"Device has no capability {capability_id!r}; add it to the "
                "driver's capabilities before registering it"
            )
        if domain not in DOMAINS:
            raise ValueError(
                f"Unknown ESPHome domain {domain!r}; expected one of "
                f"{', '.join(DOMAINS)}"
            )
        system = lookup(capability_id, domain)
        report = report_parser or (system.report_parser if system else None)
        setter = set_parser or (system.set_parser if system else None)
        base = capability_base(capability_id)
        in_multi = any(
            base in group.capabilities for group in multi_capabilities(domain)
        )
        if report is None and setter is None and not in_multi:
            if reports_only(domain) and base in SETTABLE:
                raise ValueError(
                    f"A {domain} only reports, and {capability_id!r} can be set "
                    "in Homey; bind a capability that only shows a value, or "
                    "pass report_parser and make it read-only in "
                    "capabilitiesOptions"
                )
            raise ValueError(
                f"No system capability {capability_id!r} for a {domain}; pass "
                "report_parser or set_parser"
            )

        if capability_id in self._bindings:
            self.unregister_capability(capability_id)
        ref: EntityRef = (domain, name, device_id)
        self._bindings[capability_id] = _Binding(
            capability_id=capability_id,
            entity=ref,
            report_parser=report,
            set_parser=setter,
            custom_set=set_parser is not None,
        )
        self._groups.setdefault(ref, []).append(capability_id)
        if setter is not None:
            device.register_capability_listener(
                capability_id, self._set_listener(capability_id)
            )
        self._register_multi(ref)
        if self._listed:
            self._resolve(ref)
            self._replay(ref, capability_id)

    def unregister_capability(self, capability_id: str) -> None:
        """Stop reporting and setting a capability; the capability stays."""
        binding = self._bindings.pop(capability_id, None)
        if binding is None:
            return
        group = self._groups.get(binding.entity, [])
        if capability_id in group:
            group.remove(capability_id)
        # The SDK has no way to remove a listener; drop it from its table.
        self._device._capability_listeners.pop(capability_id, None)

    def register_state_listener(
        self,
        domain: str,
        name: str,
        listener: StateListener,
        *,
        device_id: int = 0,
    ) -> None:
        """Call ``listener`` with every state of an entity.

        Raises:
            ValueError: The domain is unknown.
        """
        if domain not in DOMAINS:
            raise ValueError(f"Unknown ESPHome domain {domain!r}")
        ref: EntityRef = (domain, name, device_id)
        self._listeners.setdefault(ref, []).append(listener)
        if self._listed:
            self._resolve(ref)

    def entity(self, domain: str, name: str, device_id: int = 0) -> BoundEntity | None:
        """The entity on the current connection, or ``None`` when it is missing."""
        ref: EntityRef = (domain, name, device_id)
        info = self._infos.get(ref)
        if info is None:
            return None
        return BoundEntity(
            device=self._device,
            info=info,
            domain=domain,
            capabilities=self._groups.setdefault(ref, []),
        )

    # --- connection ---------------------------------------------------------

    def bind(self, entities: Iterable[EntityInfo]) -> None:
        """Index the entities of a new connection and resolve every binding.

        Runs before the session subscribes to states, so the connect dump
        reaches every bound capability.
        """
        self._infos = {}
        self._by_key = {}
        self._last_states = {}
        for info in entities:
            domain = domain_of(info)
            if domain is None:
                continue
            ref: EntityRef = (domain, info.name, info.device_id)
            self._infos[ref] = info
            self._by_key[(info.device_id, info.key)] = ref
        self._listed = True
        for ref in {binding.entity for binding in self._bindings.values()}:
            self._resolve(ref)
        for ref in self._listeners:
            self._resolve(ref)

    def unbind(self) -> None:
        """Forget the entities of a closed connection."""
        self._listed = False
        self._infos = {}
        self._by_key = {}
        self._last_states = {}

    def _resolve(self, ref: EntityRef) -> None:
        if ref not in self._infos:
            domain, name, device_id = ref
            where = f" on sub-device {device_id}" if device_id else ""
            self._device.error(
                f"No {domain} entity named {name!r}{where}; "
                f"{', '.join(self._groups.get(ref, [])) or 'its listener'} "
                "stays unbound"
            )

    def ref_for(self, state: EntityState) -> EntityRef | None:
        """The entity a state belongs to on the current connection."""
        return self._by_key.get((state.device_id, state.key))

    # --- node -> Homey ------------------------------------------------------

    def handle_state(self, state: EntityState) -> None:
        """Write a state to the capabilities bound to its entity, then listeners.

        Runs inline in the Native API read callback; Homey writes run as tasks.
        """
        ref = self.ref_for(state)
        if ref is None:
            return
        self._last_states[ref] = state
        entity = self.entity(*ref)
        if entity is None:
            return
        for capability_id in list(self._groups.get(ref, [])):
            self._report(capability_id, state, entity)
        for listener in self._listeners.get(ref, []):
            self._call_listener(listener, state, entity)

    def _replay(self, ref: EntityRef, capability_id: str) -> None:
        """Write the last state to a capability bound after the connect dump."""
        state = self._last_states.get(ref)
        entity = self.entity(*ref)
        if state is not None and entity is not None:
            self._report(capability_id, state, entity)

    def _report(
        self, capability_id: str, state: EntityState, entity: BoundEntity
    ) -> None:
        binding = self._bindings.get(capability_id)
        if binding is None or binding.report_parser is None:
            return
        if _no_reading(state):
            # Unknown, without asking the parser.
            value: Any = None
        else:
            try:
                value = binding.report_parser(state, entity)
            except Exception as error:
                self._device.error(f"Could not parse {capability_id}:", error)
                return
            if value is None:
                return
            if isinstance(value, float) and not math.isfinite(value):
                # Homey's IPC is strict JSON, which has no NaN or Infinity.
                value = None
        self._spawn(self._device.set_capability_value(capability_id, value))

    def _call_listener(
        self, listener: StateListener, state: EntityState, entity: BoundEntity
    ) -> None:
        try:
            result = listener(state, entity)
        except Exception as error:
            self._device.error("State listener failed:", error)
            return
        if inspect.isawaitable(result):
            self._spawn(result)

    def _spawn(self, awaitable: Awaitable[Any]) -> None:
        task = asyncio.ensure_future(awaitable)
        task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Future[Any]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            self._device.error(error)

    # --- Homey -> node ------------------------------------------------------

    def _set_listener(self, capability_id: str) -> Callable[..., Awaitable[None]]:
        async def listener(value: Any, **opts: Any) -> None:
            binding = self._bindings.get(capability_id)
            if binding is None or binding.set_parser is None:
                return
            entity = self._require_entity(binding.entity)
            kwargs = binding.set_parser(value, opts, entity)
            if kwargs is not None:
                self._send(entity, kwargs)

        return listener

    def _register_multi(self, ref: EntityRef) -> None:
        """Register a MULTI group once all its capabilities are bound to ``ref``."""
        domain = ref[0]
        group = self._groups.get(ref, [])
        for multi in multi_capabilities(domain):
            members = _members(multi, group)
            if members is None:
                continue
            if any(self._bindings[member].custom_set for member in members):
                continue
            self._device.register_multiple_capability_listener(
                list(members), self._multi_listener(ref, multi, members)
            )

    def _multi_listener(
        self, ref: EntityRef, multi: MultiCapability, members: tuple[str, ...]
    ) -> Callable[..., Awaitable[None]]:
        async def listener(values: Mapping[str, Any], **opts: Any) -> None:
            if any(member not in self._bindings for member in members):
                return
            entity = self._require_entity(ref)
            by_base = {capability_base(key): value for key, value in values.items()}
            kwargs = multi.set_parser(by_base, opts, entity)
            if kwargs is not None:
                self._send(entity, kwargs)

        return listener

    def _require_entity(self, ref: EntityRef) -> BoundEntity:
        """The live entity, or raise a message Homey shows to the user."""
        self._device._require_client()
        entity = self.entity(*ref)
        if entity is None:
            domain, name, _device_id = ref
            raise RuntimeError(
                self._device.homey.translate(
                    "errors.entity_missing", domain=domain, name=name
                )
            )
        return entity

    def _send(self, entity: BoundEntity, kwargs: Mapping[str, Any]) -> None:
        extra = dict(kwargs)
        if entity.info.device_id:
            extra["device_id"] = entity.info.device_id
        self._device._require_client().command(
            f"{entity.domain}_command", entity.key, **extra
        )


def _members(multi: MultiCapability, group: list[str]) -> tuple[str, ...] | None:
    """The bound capability for each base of ``multi``; ``None`` if one is missing."""
    found: list[str] = []
    for base in multi.capabilities:
        match = next((cap for cap in group if capability_base(cap) == base), None)
        if match is None:
            return None
        found.append(match)
    return tuple(found)


def _no_reading(state: EntityState) -> bool:
    """Whether the node has no value yet: a missing state, NaN or Infinity."""
    if getattr(state, "missing_state", False):
        return True
    value = getattr(state, "state", None)
    return isinstance(value, float) and not math.isfinite(value)
