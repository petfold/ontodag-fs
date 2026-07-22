"""The seam between ontodag-fs and the concept index (OntoDAG).

ontodag-fs codes against this Protocol (DESIGN_DECISIONS.md #13). The real
implementation will live in the ontodag repo, modeling objects as leaf Items
named by their Swarm reference (#12); `InMemoryIndex` in `memory.py` is the
reference implementation used by the test suite.

All `intent` arguments are attribute sets already closed under implication
(pass them through `closure()` first); implementations may assume this.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol, runtime_checkable


class UnknownAttributeError(KeyError):
    """An attribute name that is not present in the lattice."""


@dataclass(frozen=True)
class ObjectInfo:
    """A classified object. Identity is `ref`; `label` is display metadata."""

    ref: str                  # Swarm reference (64/128 hex chars)
    label: str                # display filename — never an identifier
    intent: frozenset[str]    # attribute set, closed under implication


@runtime_checkable
class ConceptIndex(Protocol):
    def closure(self, attrs: Iterable[str]) -> frozenset[str]:
        """FCA closure (implication-completion) of an attribute set.

        Raises UnknownAttributeError if any attribute is not in the lattice.
        closure(∅) is the top concept's intent.
        """
        ...

    def children(self, intent: frozenset[str]) -> frozenset[str]:
        """Attribute names denoting the immediate sub-concepts of `intent`.

        Per SPEC §2: only attributes that refine the current extent — skip
        those yielding an identical or empty extent, and skip attributes
        whose refined extent is strictly contained in another candidate's
        (those name deeper, non-immediate concepts).
        """
        ...

    def objects_at(self, intent: frozenset[str]) -> tuple[ObjectInfo, ...]:
        """Objects whose object concept is exactly `intent` (maximally
        described by it — nothing more specific applies)."""
        ...

    def extent(self, intent: frozenset[str]) -> tuple[ObjectInfo, ...]:
        """All objects at or below `intent` (the full extent, for `.all/`).

        Unfiled objects (empty intent) are excluded from all extents; they
        are reachable only via `unfiled()`.
        """
        ...

    def unfiled(self) -> tuple[ObjectInfo, ...]:
        """Objects known to the index with an empty/retracted intent."""
        ...

    def get_object(self, ref: str) -> ObjectInfo | None:
        """Look an object up by its Swarm reference."""
        ...

    def generation(self) -> int:
        """Monotonic counter bumped on every mutation, for cache
        invalidation (SPEC §4)."""
        ...
