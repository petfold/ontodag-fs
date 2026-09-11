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

    def display_name(self, attr: str) -> str:
        """A readable spelling of an attribute name, for listings only.

        Display-only and lossy in one direction: the returned spelling must
        still resolve through `closure()` to the same concept, but it is never
        an identity and must never be stored or compared against an intent.
        Identity for implementations without a surface layer.

        Rendering lives behind this seam because it needs the DAG (a name's
        kind comes from its declarations), and fs.py only ever sees a
        ConceptIndex — DESIGN_DECISIONS.md #13.
        """
        ...

    def generation(self) -> int:
        """Monotonic counter bumped on every mutation, for cache
        invalidation (SPEC §4)."""
        ...

    # -- filing (v0.1) ------------------------------------------------------
    #
    # Writes are classification; bytes never move (DESIGN_DECISIONS #7).
    # Every method below is a pure index edit and bumps `generation()`.

    def add_object(self, ref: str, label: str, attrs: Iterable[str] = ()) -> None:
        """File `ref` under `attrs` (raw attribute names; the implementation
        canonicalizes/closes). Filing a known ref again is an intent UNION —
        dedup by content address — and a non-empty `label` replaces the old
        one. Raises UnknownAttributeError for an attribute not in the
        lattice."""
        ...

    def asserted(self, ref: str) -> frozenset[str]:
        """The attributes *asserted* for `ref` — its direct classifications,
        canonical names, not their closure. Empty for an unfiled object.
        Raises KeyError for an unknown ref."""
        ...

    def retract(self, ref: str, attrs: Iterable[str]) -> None:
        """Drop these asserted attributes from `ref` (names not asserted are
        ignored). An object left with none is *unfiled* — it stays known and
        reachable under `/.unfiled/`; nothing is deleted."""
        ...

    def relabel(self, ref: str, label: str) -> None:
        """Change the display label. Identity is untouched."""
        ...

    def remove_object(self, ref: str) -> None:
        """Forget `ref` entirely: the index no longer knows it. The bytes
        stay on Swarm regardless — content addressing has no delete."""
        ...

    def persist(self) -> None:
        """Make prior mutations durable if the backing store needs telling
        (an EagerOntoDAG commits a new version; an in-memory index does
        nothing). The filesystem calls this once per write operation, so a
        `mv` is one version, not two."""
        ...
