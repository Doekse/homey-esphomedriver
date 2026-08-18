"""CLI entry for ``python -m homey_esphomedriver``.

Same as the ``esphome-homey`` console script.
"""

from __future__ import annotations

import sys

from homey_esphomedriver.bootstrap import main

if __name__ == "__main__":
    sys.exit(main())
