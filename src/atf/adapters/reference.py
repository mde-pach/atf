"""Find-only adapter for resources that must already exist in the environment."""

from __future__ import annotations

from typing_extensions import override

from ..catalog import Node
from . import Context, Record
from .rest import RestAdapter


class ReferenceAdapter(RestAdapter):
    """A `RestAdapter` that refuses to create or delete anything."""

    @override
    def create(self, node: Node, body: Record, ctx: Context) -> Record:
        raise ValueError(
            f"{node.id}: {node.resource!r} is a reference resource and must already exist in {ctx.env}"
        )

    @override
    def delete(self, node: Node, record: Record, ctx: Context) -> None:
        return None
