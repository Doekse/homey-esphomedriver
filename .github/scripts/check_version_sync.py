#!/usr/bin/env python3
"""Fail if pyproject.toml version and __init__.__version__ disagree."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

INIT_PATH = Path("src/homey_esphomedriver/__init__.py")
VERSION_RE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)


def main() -> int:
    """Compare package metadata version to the runtime ``__version__`` string."""
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    project_version = pyproject["project"]["version"]
    match = VERSION_RE.search(INIT_PATH.read_text(encoding="utf-8"))
    if match is None:
        print(f"Could not parse __version__ from {INIT_PATH}", file=sys.stderr)
        return 1
    init_version = match.group(1)
    if init_version != project_version:
        print(
            f"Version mismatch: {INIT_PATH}={init_version!r} "
            f"pyproject.toml={project_version!r}",
            file=sys.stderr,
        )
        return 1
    print(init_version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
