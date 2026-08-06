"""Load ATF's plugin the way a suite's `atf.yaml` would cause it to be loaded."""

from __future__ import annotations

import sys
from pathlib import Path

here = Path(__file__).parent
sys.path.insert(0, str(here))
# `lineage/explicit.py` is the declaration layer the other half of Phase 0 settled on. The two
# prototypes share it rather than each keeping a copy, so wiring them together is the check.
sys.path.insert(0, str(here.parent))

pytest_plugins = ["atf_plugin", "atf_steps"]
