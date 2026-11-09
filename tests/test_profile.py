"""BrandProfile parsing and filtering tests.

Brand apps declare an ``esphome`` object in ``driver.compose.json``. These tests
pin the compose keys and the project-acceptance rules that decide which driver
claims a node.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from homey_esphomedriver.profile import (
    DEFAULT_BRAND_PROFILE,
    DEFAULT_CLIENT_INFO,
    BrandProfile,
)


@pytest.mark.parametrize(
    "manifest", [None, {}, {"id": "my-driver"}, {"esphome": "not-a-mapping"}]
)
def test_from_manifest_without_esphome_object_is_the_default(manifest: Any) -> None:
    assert BrandProfile.from_manifest(manifest) == DEFAULT_BRAND_PROFILE


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


@pytest.mark.parametrize(
    "key",
    [
        "hidden_entities",
        "projectNames",
        # Capability keys from before register_capability.
        "hiddenEntities",
        "deviceEntities",
        "capabilityOverrides",
        "deviceClassOverrides",
        "maintenanceActions",
    ],
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


def test_native_app_suggestion() -> None:
    profile = BrandProfile.from_compose({"nativeApps": {"Brand.AQ-1": "Brand"}})
    assert profile.native_app_suggestion("Brand.AQ-1") == "Brand"
    assert profile.native_app_suggestion("Unknown") is None


def test_replace_returns_a_modified_copy() -> None:
    profile = BrandProfile.from_compose({"clientInfo": "Original"})
    updated = profile.replace(client_info="Changed")
    assert profile.client_info == "Original"
    assert updated.client_info == "Changed"
