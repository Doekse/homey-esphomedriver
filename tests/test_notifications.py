"""Timeline notification when a firmware sync adds or removes entities."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from homey_esphomedriver.notifications import notify_entities_changed

_LOCALES = (
    "en",
    "nl",
    "de",
    "fr",
    "it",
    "sv",
    "no",
    "es",
    "da",
    "ru",
    "pl",
    "ko",
    "ar",
)
_TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "homey_esphomedriver"
    / "homey_template"
)


def _homey() -> SimpleNamespace:
    homey = SimpleNamespace(
        notifications=SimpleNamespace(create_notification=AsyncMock()),
        calls=[],
    )

    def translate(key: str, **tags: str) -> str:
        homey.calls.append((key, tags))
        return key

    homey.translate = translate
    return homey


def _notify(**kwargs: Any) -> SimpleNamespace:
    homey = _homey()
    asyncio.run(notify_entities_changed(homey=homey, device_name="Kitchen", **kwargs))
    return homey


def test_disabled_skips_notification() -> None:
    homey = _notify(added=["onoff.a"], removed=[], enabled=False)

    assert homey.calls == []
    homey.notifications.create_notification.assert_not_awaited()


def test_empty_change_skips_notification() -> None:
    homey = _notify(added=[], removed=[])

    assert homey.calls == []
    homey.notifications.create_notification.assert_not_awaited()


def test_additions_use_the_count() -> None:
    homey = _notify(added=["onoff.a", "onoff.b"], removed=[])

    assert homey.calls == [
        (
            "notifications.entities_changed",
            {
                "device": "**Kitchen**",
                "added": "2",
                "removed": "0",
            },
        )
    ]
    homey.notifications.create_notification.assert_awaited_once_with(
        "notifications.entities_changed"
    )


def test_removals_use_the_count() -> None:
    homey = _notify(added=["onoff.new"], removed=["Relay", "Pump"])

    assert homey.calls == [
        (
            "notifications.entities_changed_removed",
            {
                "device": "**Kitchen**",
                "added": "1",
                "removed": "2",
            },
        )
    ]
    homey.notifications.create_notification.assert_awaited_once_with(
        "notifications.entities_changed_removed"
    )


def test_notification_copy_is_translated() -> None:
    """Every template locale and the settings checkbox carry this notification."""
    for code in _LOCALES:
        data = json.loads((_TEMPLATE / "locales" / f"{code}.json").read_text())
        notes = data["notifications"]
        added = notes["entities_changed"]
        removed = notes["entities_changed_removed"]
        assert "__device__" in added
        assert "__added__" in added
        assert "__device__" in removed
        assert "__added__" in removed
        assert "__removed__" in removed
        assert "Flow" in removed

    settings = json.loads(
        (
            _TEMPLATE / "compose" / "drivers" / "templates" / "esphome-defaults.json"
        ).read_text()
    )
    groups = settings["settings"]
    index = next(
        i for i, group in enumerate(groups) if group.get("id") == "notifications"
    )
    info = next(
        i for i, group in enumerate(groups) if group.get("id") == "device_information"
    )
    assert index < info
    previous = groups[index - 1]
    assert any(child.get("id") == "show_diagnostics" for child in previous["children"])
    group = groups[index]
    child = group["children"][0]
    assert child["id"] == "notify_entities_changed"
    assert child["type"] == "checkbox"
    assert child["value"] is True
    for lang in _LOCALES:
        assert group["label"][lang]
        assert child["label"][lang]
        assert child["hint"][lang]
