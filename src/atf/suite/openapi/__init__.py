"""Deriving catalog resource types from an OpenAPI schema."""

from __future__ import annotations

from .document import SchemaError, headers_for, is_url, read, type_name
from .score import Collection, Guess, collections, convention_of, guess_key
from .write import Proposal, key_said, propose, render

__all__ = [
    "Collection",
    "Guess",
    "Proposal",
    "SchemaError",
    "collections",
    "convention_of",
    "guess_key",
    "headers_for",
    "is_url",
    "key_said",
    "propose",
    "read",
    "render",
    "type_name",
]
