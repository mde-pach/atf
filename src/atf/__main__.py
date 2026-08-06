"""`python -m atf` — the command line."""

from __future__ import annotations

import sys

from .entry import main

if __name__ == "__main__":
    sys.exit(main())
