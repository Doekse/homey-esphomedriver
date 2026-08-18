"""Copy package Homey Compose files into a brand or generic Homey app.

Shared Compose (defaults, pair HTML, Flow cards, locales, SVGs) is refreshed
on every run. Brand-owned files (app.json, driver.compose.json, driver
entrypoints) are created once and left alone unless ``--force``.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

_DRIVER_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PLACEHOLDER_RE = re.compile(r"__([A-Z0-9_]+)__")
_FLOW_TYPES = ("triggers", "conditions", "actions")

TEMPLATE_ROOT = Path(__file__).resolve().parent / "homey_template"


@dataclass(frozen=True)
class BootstrapOptions:
    """Inputs for :func:`bootstrap_app`."""

    app_dir: Path
    driver_id: str | None = None
    app_id: str | None = None
    app_name: str | None = None
    brand: str | None = None
    project: str | None = None
    driver_name: str | None = None
    device_class: str = "other"
    force: bool = False


@dataclass
class BootstrapResult:
    """Relative paths written or skipped during a bootstrap run."""

    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def template_root() -> Path:
    """Return the on-disk Homey template directory shipped with this package.

    Raises:
        FileNotFoundError: If the packaged template directory is missing.
    """
    if not TEMPLATE_ROOT.is_dir():
        msg = f"Homey template directory missing: {TEMPLATE_ROOT}"
        raise FileNotFoundError(msg)
    return TEMPLATE_ROOT


def profile_constant(driver_id: str) -> str:
    """Return the ``BrandProfile`` constant name for a Homey driver id."""
    return f"{driver_id.replace('-', '_').upper()}_PROFILE"


def derive_app_id(app_dir: Path) -> str:
    """Guess a reverse-domain Homey id from a ``{brand}-homey`` directory name."""
    stem = app_dir.resolve().name.removesuffix("-homey")
    slug = re.sub(r"[^a-z0-9]+", "", stem.lower())
    return f"com.{slug or 'brand'}"


def derive_app_name(app_dir: Path, explicit: str | None = None) -> str:
    """Return the Homey app display name."""
    if explicit:
        return explicit
    stem = app_dir.resolve().name.removesuffix("-homey")
    return stem.replace("-", " ").replace("_", " ").title() or "Brand"


def derive_brand(app_name: str, explicit: str | None = None) -> str:
    """Return the ESPHome project-name prefix (no spaces)."""
    if explicit:
        return explicit
    return re.sub(r"\s+", "", app_name)


def derive_project_name(brand: str, driver_id: str, explicit: str | None = None) -> str:
    """Return the ESPHome ``project.name`` for a product driver."""
    if explicit:
        return explicit
    sku = driver_id.upper()
    return f"{brand}.{sku}"


def bootstrap_app(options: BootstrapOptions) -> BootstrapResult:
    """Copy shared templates and optionally add one product driver stub.

    Args:
        options: App directory, optional driver id, and overwrite flags.

    Returns:
        Relative paths written or skipped.
    """
    if options.driver_id is not None:
        _validate_driver_id(options.driver_id)
    app_dir = options.app_dir.expanduser().resolve()
    app_dir.mkdir(parents=True, exist_ok=True)
    result = BootstrapResult()
    root = template_root()
    app_name = derive_app_name(app_dir, options.app_name)
    app_id = options.app_id or derive_app_id(app_dir)
    brand = derive_brand(app_name, options.brand)
    client_info = f"Homey {app_name}"

    _copy_shared(root, app_dir, result)
    _write_app_stubs(
        root,
        app_dir,
        result,
        app_id=app_id,
        app_name=app_name,
        force=options.force,
    )
    if options.driver_id:
        _scaffold_driver(
            root,
            app_dir,
            result,
            driver_id=options.driver_id,
            project=derive_project_name(brand, options.driver_id, options.project),
            driver_name=options.driver_name,
            device_class=options.device_class,
            client_info=client_info,
            force=options.force,
        )
    _emit_app_flow(root, app_dir, result)
    return result


def main(argv: list[str] | None = None) -> int:
    """CLI entry for ``esphome-homey``.

    Args:
        argv: Argument list without the program name. ``None`` uses ``sys.argv``.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(
        prog="esphome-homey",
        description="Copy homey-esphomedriver Homey Compose files into a Homey app.",
        epilog="example:\n  esphome-homey sync -p /path/to/app\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")
    sync = sub.add_parser("sync", help="Refresh package-owned Homey Compose files")
    _add_path_arg(sync, "Homey app directory (default: current directory)")
    sync.add_argument(
        "--force",
        action="store_true",
        help="Overwrite app.py / app.json if they exist",
    )

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    try:
        return _cmd_sync(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _cmd_sync(args: argparse.Namespace) -> int:
    app_dir = args.path.expanduser().resolve()
    result = bootstrap_app(BootstrapOptions(app_dir=app_dir, force=args.force))
    _print_summary(result, f"Synced {app_dir}")
    return 0


def _print_summary(result: BootstrapResult, heading: str) -> None:
    skipped = f", skipped {len(result.skipped)}" if result.skipped else ""
    print(heading)
    print(f"Wrote {len(result.written)} files{skipped}")


def _add_path_arg(parser: argparse.ArgumentParser, help_text: str) -> None:
    parser.add_argument(
        "-p",
        "--path",
        type=Path,
        default=Path("."),
        help=help_text,
    )


def _validate_driver_id(driver_id: str) -> None:
    if not _DRIVER_ID_RE.fullmatch(driver_id):
        msg = (
            f"Invalid driver id {driver_id!r}; use lowercase letters, digits, "
            "and hyphens (e.g. aq-1)"
        )
        raise ValueError(msg)


def _copy_shared(root: Path, app_dir: Path, result: BootstrapResult) -> None:
    """Refresh package-owned compose, pair/repair HTML, locales, and default SVGs."""
    template = root / "compose" / "drivers" / "templates" / "esphome-defaults.json"
    dest_template = (
        app_dir / ".homeycompose" / "drivers" / "templates" / "esphome-defaults.json"
    )
    mappings: list[tuple[Path, Path, bool]] = [
        (template, dest_template, True),
        (
            root / "compose" / "discovery" / "esphome.json",
            app_dir / ".homeycompose" / "discovery" / "esphome.json",
            True,
        ),
        (root / "assets" / "icon.svg", app_dir / "assets" / "icon.svg", False),
        (root / "assets" / "logo.svg", app_dir / "assets" / "logo.svg", False),
    ]
    for src, dest, overwrite in mappings:
        _copy_file(src, dest, app_dir, result, overwrite=overwrite)
    _copy_dir(
        root / "compose" / "capabilities",
        app_dir / ".homeycompose" / "capabilities",
        app_dir,
        result,
        overwrite=True,
    )
    _copy_dir(
        root / "compose" / "drivers" / "pair",
        app_dir / ".homeycompose" / "drivers" / "pair",
        app_dir,
        result,
        overwrite=True,
    )
    for view in ("configure_manual", "enter_key"):
        _copy_dir(
            root / "compose" / "drivers" / "pair" / view,
            app_dir / ".homeycompose" / "drivers" / "repair" / view,
            app_dir,
            result,
            overwrite=True,
        )
    _copy_dir(
        root / "assets" / "capabilities",
        app_dir / "assets" / "capabilities",
        app_dir,
        result,
        overwrite=True,
    )
    _copy_dir(
        root / "assets" / "devices",
        app_dir / "assets" / "devices",
        app_dir,
        result,
        overwrite=True,
    )
    _merge_locales(root / "locales", app_dir / "locales", app_dir, result)


def _write_app_stubs(
    root: Path,
    app_dir: Path,
    result: BootstrapResult,
    *,
    app_id: str,
    app_name: str,
    force: bool,
) -> None:
    stubs = root / "stubs"
    mapping = {
        "APP_ID": app_id,
        "APP_NAME": app_name,
    }
    _write_text(
        _render(stubs / "app.py", mapping),
        app_dir / "app.py",
        app_dir,
        result,
        overwrite=force,
    )
    _write_text(
        _render(stubs / "app.json", mapping),
        app_dir / ".homeycompose" / "app.json",
        app_dir,
        result,
        overwrite=force,
    )


def _scaffold_driver(
    root: Path,
    app_dir: Path,
    result: BootstrapResult,
    *,
    driver_id: str,
    project: str,
    driver_name: str | None,
    device_class: str,
    client_info: str,
    force: bool,
) -> None:
    driver_dir = app_dir / "drivers" / driver_id
    mapping = {
        "DRIVER_NAME": driver_name or driver_id.upper(),
        "DEVICE_CLASS": device_class,
        "CLIENT_INFO": client_info,
        "PROJECT_NAME": project,
    }
    stubs = root / "stubs"
    _write_text(
        _render(stubs / "driver.py", mapping),
        driver_dir / "driver.py",
        app_dir,
        result,
        overwrite=force,
    )
    _write_text(
        (stubs / "device.py").read_text(encoding="utf-8"),
        driver_dir / "device.py",
        app_dir,
        result,
        overwrite=force,
    )
    _write_text(
        _render(stubs / "driver.compose.json", mapping),
        driver_dir / "driver.compose.json",
        app_dir,
        result,
        overwrite=force,
    )
    _copy_file(
        root / "driver_assets" / "icon.svg",
        driver_dir / "assets" / "icon.svg",
        app_dir,
        result,
        overwrite=False,
    )
    _copy_file(
        root / "driver_assets" / "icon-ip.svg",
        driver_dir / "assets" / "icon-ip.svg",
        app_dir,
        result,
        overwrite=True,
    )
    _copy_file(
        root / "driver_assets" / "icon-bluetooth.svg",
        driver_dir / "assets" / "icon-bluetooth.svg",
        app_dir,
        result,
        overwrite=True,
    )


def _emit_app_flow(root: Path, app_dir: Path, result: BootstrapResult) -> None:
    """Write app-level Flow cards from the monolithic authoring JSON."""
    src = json.loads((root / "driver.flow.compose.json").read_text(encoding="utf-8"))
    driver_ids = _driver_ids(app_dir)
    for kind in _FLOW_TYPES:
        dest_dir = app_dir / ".homeycompose" / "flow" / kind
        dest_dir.mkdir(parents=True, exist_ok=True)
        for raw in src.get(kind, []):
            card = deepcopy(raw)
            card_id = card["id"]
            card_filter = card.pop("$filter", None)
            args = list(card.get("args", []))
            card["args"] = [
                {
                    "type": "device",
                    "name": "device",
                    "filter": _device_arg_filter(driver_ids, card_filter),
                },
                *args,
            ]
            _write_text(
                json.dumps(card, indent=2, ensure_ascii=False) + "\n",
                dest_dir / f"{card_id}.json",
                app_dir,
                result,
                overwrite=True,
            )


def _driver_ids(app_dir: Path) -> list[str]:
    """Return sorted Homey driver folder names under ``drivers/``."""
    drivers = app_dir / "drivers"
    if not drivers.is_dir():
        return []
    return sorted(
        path.name
        for path in drivers.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    )


def _device_arg_filter(driver_ids: list[str], card_filter: str | None) -> str:
    """Build a Homey device-arg filter from driver ids and a card ``$filter``."""
    parts: list[str] = []
    if driver_ids:
        parts.append("driver_id=" + "|".join(driver_ids))
    if card_filter:
        parts.append(card_filter)
    return "&".join(parts)


def _render(src: Path, mapping: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return mapping.get(key, match.group(0))

    return _PLACEHOLDER_RE.sub(replace, src.read_text(encoding="utf-8"))


def _copy_dir(
    src: Path,
    dest: Path,
    app_dir: Path,
    result: BootstrapResult,
    *,
    overwrite: bool,
) -> None:
    for path in _iter_files(src):
        _copy_file(
            path,
            dest / path.relative_to(src),
            app_dir,
            result,
            overwrite=overwrite,
        )


def _iter_files(root: Path) -> Iterator[Path]:
    yield from sorted(p for p in root.rglob("*") if p.is_file())


def _copy_file(
    src: Path,
    dest: Path,
    app_dir: Path,
    result: BootstrapResult,
    *,
    overwrite: bool,
) -> None:
    rel = _rel(dest, app_dir)
    if dest.exists() and not overwrite:
        result.skipped.append(rel)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    result.written.append(rel)


def _write_text(
    contents: str,
    dest: Path,
    app_dir: Path,
    result: BootstrapResult,
    *,
    overwrite: bool,
) -> None:
    rel = _rel(dest, app_dir)
    if dest.exists() and not overwrite:
        result.skipped.append(rel)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(contents, encoding="utf-8")
    result.written.append(rel)


def _merge_locales(
    src_dir: Path,
    dest_dir: Path,
    app_dir: Path,
    result: BootstrapResult,
) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    for src in _iter_files(src_dir):
        dest = dest_dir / src.relative_to(src_dir)
        incoming = json.loads(src.read_text(encoding="utf-8"))
        if dest.exists():
            existing = json.loads(dest.read_text(encoding="utf-8"))
            merged = _deep_merge(existing, incoming)
        else:
            merged = incoming
        dest.write_text(
            json.dumps(merged, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        result.written.append(_rel(dest, app_dir))


def _deep_merge(base: object, overlay: object) -> object:
    if isinstance(base, dict) and isinstance(overlay, dict):
        out = dict(base)
        for key, value in overlay.items():
            out[key] = _deep_merge(out[key], value) if key in out else value
        return out
    return overlay


def _rel(path: Path, app_dir: Path) -> str:
    return path.resolve().relative_to(app_dir).as_posix()


if __name__ == "__main__":
    sys.exit(main())
