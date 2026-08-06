"""`python -m atf` — the command line for the design in `docs-next/`.

The `atf` console script still points at the older design's CLI, because the suite under `tests/`
drives it. This is the same command tree that becomes `atf` when that suite is replaced.
"""

from __future__ import annotations

import sys

from .entry import main

if __name__ == "__main__":
    sys.exit(main())
