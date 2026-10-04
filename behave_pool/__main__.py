"""Support ``python -m behave_pool`` as an alias for the behave-pool CLI."""

from __future__ import annotations

import sys

from behave_pool.cli import main

if __name__ == "__main__":
    sys.exit(main())
