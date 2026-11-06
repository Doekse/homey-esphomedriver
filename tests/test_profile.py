"""BrandProfile parsing and filtering tests.

Brand apps declare an ``esphome`` object in ``driver.compose.json``. These tests
pin the compose keys, the project-acceptance rules that decide which driver
claims a node, and the capability override precedence.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import pytest
from aioesphomeapi import EntityInfo

from homey_esphomedriver.profile import (
    DEFAULT_BRAND_PROFILE,
    DEFAULT_CLIENT_INFO,
    BrandProfile,
)


def entity(object_id: str, key: int = 1) -> EntityInfo:
    return EntityInfo(object_id=object_id, key=key, name=object_id)


@pytest.mark.parametrize(
    "manifest", [None, {}, {"id": "my-driver"}, {"esphome": "not-a-mapping"}]
)
def test_from_manifest_without_esphome_object_is_the_default(manifest: Any) -> None:
    assert BrandProfile.from_manifest(manifest) == DEFAULT_BRAND_PROFILE


class _HookedProfile(BrandProfile):
    def after_map(self, entities: Sequence[EntityInfo], homey_device: Any) -> None:
        homey_device["tagged"] = [entity.object_id for entity in entities]


@pytest.mark.parametrize(
    "manifest", [{}, {"esphome": {"hiddenEntities": ["status_led"]}}]
)
def test_from_manifest_keeps_the_subclass(manifest: dict[str, Any]) -> None:
    """A brand subclass keeps its hooks with or without an esphome object."""
    profile = _HookedProfile.from_manifest(manifest)
    assert type(profile) is _HookedProfile
    device: dict[str, Any] = {}
    profile.after_map([entity("relay")], device)  # type: ignore[arg-type]
    assert device == {"tagged": ["relay"]}


def test_from_manifest_reads_nested_esphome_object() -> None:
    profile = BrandProfile.from_manifest({"esphome": {"projects": ["Brand.AQ-1"]}})
    assert profile.projects == frozenset({"Brand.AQ-1"})


def test_default_profile_accepts_every_project() -> None:
    """The generic io.esphome app omits projects, so nothing is filtered out."""
    assert DEFAULT_BRAND_PROFILE.accepts_project("Anything.At-All")
    assert DEFAULT_BRAND_PROFILE.accepts_discovery({})
    assert DEFAULT_BRAND_PROFILE.client_info == DEFAULT_CLIENT_INFO


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        ({"clientInfo": "Brand App"}, "Brand App"),
        ({}, DEFAULT_CLIENT_INFO),
    ],
)
def test_client_info(keys: dict[str, Any], expected: str) -> None:
    assert BrandProfile.from_compose(keys).client_info == expected


def test_projects() -> None:
    profile = BrandProfile.from_compose({"projects": ["Brand.AQ-1", "Brand.AQ-2"]})
    assert profile.projects == frozenset({"Brand.AQ-1", "Brand.AQ-2"})


def test_project_prefix() -> None:
    profile = BrandProfile.from_compose({"projectPrefix": "Brand."})
    assert profile.project_prefix == ("Brand.",)


def test_hidden_entities() -> None:
    profile = BrandProfile.from_compose({"hiddenEntities": ["status_led"]})
    assert profile.skip_entity(entity("status_led")) is True
    assert profile.skip_entity(entity("relay")) is False


@pytest.mark.parametrize(
    "key", ["hidden_entities", "skipObjectIds", "projectNames", "hiddenEntites"]
)
def test_unknown_key_is_logged_and_ignored(
    key: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Old aliases and typos would otherwise do nothing without a word."""
    with caplog.at_level(logging.WARNING, logger="homey_esphomedriver.profile"):
        profile = BrandProfile.from_compose({key: ["status_led"]})
    assert profile == DEFAULT_BRAND_PROFILE
    assert key in caplog.text


def test_scalar_string_is_accepted_where_a_list_is_expected() -> None:
    """Compose authors write a bare string as often as a list."""
    profile = BrandProfile.from_compose({"projects": "Brand.AQ-1"})
    assert profile.projects == frozenset({"Brand.AQ-1"})


def test_accepts_project_by_exact_name() -> None:
    profile = BrandProfile.from_compose({"projects": ["Brand.AQ-1"]})
    assert profile.accepts_project("Brand.AQ-1") is True
    assert profile.accepts_project("Brand.AQ-2") is False


def test_accepts_project_by_prefix() -> None:
    profile = BrandProfile.from_compose({"projectPrefix": ["Brand."]})
    assert profile.accepts_project("Brand.AQ-9") is True
    assert profile.accepts_project("Other.AQ-9") is False


def test_projects_and_prefix_are_ored() -> None:
    profile = BrandProfile.from_compose(
        {"projects": ["Exact.One"], "projectPrefix": ["Brand."]}
    )
    assert profile.accepts_project("Exact.One") is True
    assert profile.accepts_project("Brand.Whatever") is True
    assert profile.accepts_project("Nope.Nope") is False


def test_empty_projects_list_accepts_nothing() -> None:
    """An explicit empty list is a filter, unlike an absent key."""
    profile = BrandProfile.from_compose({"projects": []})
    assert profile.projects == frozenset()
    assert profile.accepts_project("Brand.AQ-1") is False


def test_accepts_discovery_reads_txt_project_name() -> None:
    profile = BrandProfile.from_compose({"projects": ["Brand.AQ-1"]})
    assert profile.accepts_discovery({"project_name": "Brand.AQ-1"}) is True
    assert profile.accepts_discovery({"project_name": "Other"}) is False


def test_accepts_discovery_without_project_name_is_rejected_when_filtered() -> None:
    """A node advertising no project cannot satisfy a projects filter."""
    profile = BrandProfile.from_compose({"projects": ["Brand.AQ-1"]})
    assert profile.accepts_discovery({}) is False


def test_capability_id_for_returns_default_when_unmapped() -> None:
    assert DEFAULT_BRAND_PROFILE.capability_id_for(entity("relay"), "onoff") == "onoff"


def test_capability_id_for_uses_device_entities() -> None:
    profile = BrandProfile.from_compose({"deviceEntities": {"relay": "onoff.pump"}})
    assert profile.capability_id_for(entity("relay"), "onoff") == "onoff.pump"


def test_capability_overrides_take_precedence_over_device_entities() -> None:
    """The (object_id, default) pair is more specific, so it wins."""
    profile = BrandProfile(
        device_entities={"relay": "onoff.generic"},
        capability_overrides={("relay", "onoff"): "onoff.specific"},
    )
    assert profile.capability_id_for(entity("relay"), "onoff") == "onoff.specific"


def test_capability_overrides_fall_through_on_different_default() -> None:
    profile = BrandProfile(
        device_entities={"relay": "onoff.generic"},
        capability_overrides={("relay", "button"): "onoff.specific"},
    )
    assert profile.capability_id_for(entity("relay"), "onoff") == "onoff.generic"


def test_capability_overrides_parses_nested_compose_mapping() -> None:
    profile = BrandProfile.from_compose(
        {"capabilityOverrides": {"relay": {"onoff": "onoff.pump"}}}
    )
    assert profile.capability_overrides == {("relay", "onoff"): "onoff.pump"}


def test_capability_overrides_skips_malformed_entries() -> None:
    profile = BrandProfile.from_compose({"capabilityOverrides": {"relay": "not-a-map"}})
    assert profile.capability_overrides == {}


def test_device_class_for_returns_none_without_entity() -> None:
    profile = BrandProfile.from_compose({"deviceClassOverrides": {"relay": "socket"}})
    assert profile.device_class_for(None, None) is None
    assert profile.device_class_for(None, entity("relay")) == "socket"
    assert profile.device_class_for(None, entity("other")) is None


def test_native_app_suggestion() -> None:
    profile = BrandProfile.from_compose({"nativeApps": {"Brand.AQ-1": "Brand"}})
    assert profile.native_app_suggestion("Brand.AQ-1") == "Brand"
    assert profile.native_app_suggestion("Unknown") is None


def test_replace_returns_a_modified_copy() -> None:
    profile = BrandProfile.from_compose({"clientInfo": "Original"})
    updated = profile.replace(client_info="Changed")
    assert profile.client_info == "Original"
    assert updated.client_info == "Changed"


def test_after_map_default_is_a_noop() -> None:
    assert DEFAULT_BRAND_PROFILE.after_map([entity("relay")], None) is None


@pytest.mark.parametrize(
    ("object_id", "hidden"),
    [
        ("debug_uptime", True),
        ("debug_free_heap", True),
        ("uptime", False),
        ("wifi_signal", True),
        ("wifi_signal_db", False),
    ],
)
def test_hidden_entities_accepts_patterns(object_id: str, hidden: bool) -> None:
    """A family of entities can be named once instead of enumerated.

    Object ids are slugified to ``[a-z0-9_-]``, so ``*``/``?``/``[`` cannot occur
    in a literal id and are unambiguous as wildcards.
    """
    profile = BrandProfile.from_compose({"hiddenEntities": ["debug_*", "wifi_signal"]})
    assert profile.skip_entity(entity(object_id)) is hidden


def test_hidden_entities_without_patterns_still_matches_exactly() -> None:
    profile = BrandProfile.from_compose({"hiddenEntities": ["relay"]})
    assert profile.skip_entity(entity("relay")) is True
    assert profile.skip_entity(entity("relay_2")) is False
