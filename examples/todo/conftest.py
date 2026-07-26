"""Starts the stand-in backend before ATF bootstraps, then hands over to the plugin.

The fake API must exist before `atf.plugin` imports, because bootstrap builds adapters from
`TODO_URL` at import time. Point `TODO_URL` at a real service and this block does nothing.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

if not os.environ.get("TODO_URL"):
    from fake_api import TodoAPI

    os.environ.setdefault("TODO_ACTOR", "example")
    _api = TodoAPI(actor=os.environ["TODO_ACTOR"])
    os.environ["TODO_URL"] = _api.start()

pytest_plugins = ["atf.plugin"]
