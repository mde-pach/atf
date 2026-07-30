"""What the engine says back: where a resource stands, and what provisioning it did."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from typing_extensions import override

from ..model.records import Record
from ..model.typespec import EPHEMERAL, REFERENCE

PRESENT = "present"
ABSENT = "absent"
UNSUPPORTED = "unsupported"
ERROR = "error"
UNKNOWN = "unknown"

CREATED = "created"
EXISTS = "exists"
OBSERVED = "observed"
BLOCKED = "blocked"

# What a run cannot get past on its own. An absent resource is not here: naming one in a scenario is
# precisely what makes ATF create it.
BLOCKING = frozenset({UNSUPPORTED, ERROR})

# What a provisioning pass would attempt. An error is included: the lookup failed, so whether the
# resource is there is unknown, and attempting it is how that gets settled.
ATTEMPTED = frozenset({ABSENT, ERROR})

# What each word means for a person, in the five names the interface has for that. Every other
# vocabulary the cockpit tones — run outcomes, scenario states — extends this one, and repeats
# none of it.
TONES = {
    PRESENT: "ok",
    CREATED: "ok",
    EXISTS: "ok",
    ABSENT: "idle",
    UNKNOWN: "idle",
    EPHEMERAL: "accent",
    REFERENCE: "accent",
    OBSERVED: "accent",
    ERROR: "bad",
    UNSUPPORTED: "warn",
    BLOCKED: "warn",
}


def tone(word: str) -> str:
    return TONES.get(word, "idle")


@dataclass(frozen=True)
class ResourceStatus:
    """Where one catalog node stands in one environment.

    `identity` and `record` are there only for a resource that is present. The record travels with
    the state: a caller offering an assertion on one of its fields needs to know which fields there
    are and what each holds right now, and reading it again asks the backend the same question twice
    per page.
    """

    state: str = UNKNOWN
    detail: str = ""
    identity: Any = None
    record: Record | None = None

    @property
    def present(self) -> bool:
        return self.state == PRESENT

    @property
    def blocking(self) -> bool:
        """Whether a run cannot get past this resource on its own."""
        return self.state in BLOCKING

    @property
    def missing(self) -> bool:
        """Whether a provisioning pass would attempt this resource."""
        return self.state in ATTEMPTED

    @property
    def tone(self) -> str:
        return tone(self.state)

    @property
    def fields(self) -> Record:
        """The record's fields, empty when there is no record to read."""
        return self.record or {}


UNKNOWN_STATUS = ResourceStatus()


class Statuses(Mapping[str, ResourceStatus]):
    """Where every catalog node stands in one environment.

    A node nobody asked about reads as `unknown` and never raises: a page renders from whatever the
    last status pass covered, and a catalog can grow between the two.
    """

    def __init__(self, entries: Mapping[str, ResourceStatus] | None = None) -> None:
        self._entries: dict[str, ResourceStatus] = dict(entries or {})

    @override
    def __getitem__(self, node_id: str) -> ResourceStatus:
        return self._entries[node_id]

    @override
    def __iter__(self) -> Iterator[str]:
        return iter(self._entries)

    @override
    def __len__(self) -> int:
        return len(self._entries)

    def of(self, node_id: str) -> ResourceStatus:
        return self._entries.get(node_id, UNKNOWN_STATUS)

    def state(self, node_id: str) -> str:
        return self.of(node_id).state

    def identity(self, node_id: str) -> Any:
        return self.of(node_id).identity

    def identities(self) -> dict[str, Any]:
        """Every node that has an identity out there, and what it is."""
        return {
            node_id: entry.identity
            for node_id, entry in self._entries.items()
            if entry.identity not in (None, "")
        }

    def count(self, state: str) -> int:
        return sum(1 for entry in self._entries.values() if entry.state == state)


@dataclass(frozen=True)
class Refusal:
    """Why ATF will not create a resource, and whether a run is stuck without it.

    A reference resource that is absent stops a scenario reaching its first `When`; an observation
    or an ephemeral one is simply not a precondition, and running is what deals with it.
    """

    why: str
    blocks: bool = False

    @property
    def creatable(self) -> bool:
        return not self.why


# What a resource ATF can make says when asked why not.
CREATABLE = Refusal(why="")


@dataclass(frozen=True)
class ProvisionResult:
    """What one node's turn in a provisioning pass did.

    `record` is what the adapter handed back, and is there for every node that succeeded.
    """

    node_id: str
    action: str
    ok: bool
    detail: str = ""
    record: Record | None = None

    @property
    def state(self) -> str:
        """A node's action is its state only when it worked: a `reference` not found failed."""
        if self.ok:
            return self.action
        return BLOCKED if self.action == BLOCKED else ERROR

    @property
    def tone(self) -> str:
        return tone(self.state)


@dataclass(frozen=True)
class ProvisionOutcome:
    """What a whole provisioning pass did, node by node, and the records it ended up holding."""

    results: list[ProvisionResult] = field(default_factory=list)
    records: dict[str, Record] = field(default_factory=dict)

    @property
    def failures(self) -> list[ProvisionResult]:
        return [result for result in self.results if not result.ok]

    @property
    def ok(self) -> bool:
        return not self.failures
