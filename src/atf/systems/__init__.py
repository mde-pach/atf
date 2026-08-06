"""The systems ATF ships — the ones it needs to test itself, and nothing more.

`command`, `browser`, `filesystem` and `process` are here, and `rest` beside them.
There is deliberately nothing that binds ATF to one database: `sqlite` throughout the documentation
is the worked example of an adapter somebody wrote, and lives in the suite that uses it.

Importing this package registers every system in it, so a manifest naming `filesystem:` settings
finds an adapter without listing anything under `extensions:`.
"""

from __future__ import annotations

from . import browser, command, filesystem, process, rest

__all__ = ["browser", "command", "filesystem", "process", "rest"]
