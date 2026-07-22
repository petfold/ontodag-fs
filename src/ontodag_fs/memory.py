"""In-memory ConceptIndex — the reference implementation of the Protocol.

Mirrors the model decided in DESIGN_DECISIONS.md #12: a DAG of named
attributes (category Items) plus objects keyed by Swarm reference, whose
closed intent is the implication-closure (ancestor set) of their asserted
attributes. The real implementation will live in the ontodag repo; keep the
observable semantics here and there identical.
"""

from __future__ import annotations

from typing import Iterable

from .index import ObjectInfo, UnknownAttributeError


def validate_attribute(name: str) -> None:
    """SPEC §1: attributes must not start with '.' and must not contain '/'."""
    if not name:
        raise ValueError("attribute name must be non-empty")
    if name.startswith("."):
        raise ValueError(f"attribute name must not start with '.': {name!r}")
    if "/" in name:
        raise ValueError(f"attribute name must not contain '/': {name!r}")


class InMemoryIndex:
    def __init__(self) -> None:
        self._parents: dict[str, set[str]] = {}       # attr -> direct supers
        self._objects: dict[str, tuple[str, frozenset[str]]] = {}  # ref -> (label, asserted attrs)
        self._generation = 0

    # ------------------------------------------------------------- building

    def add_attribute(self, name: str, parents: Iterable[str] = ()) -> None:
        """Add an attribute (category) with the given direct super-attributes.

        Parents are auto-created if absent. Re-adding unions the parent sets.
        """
        validate_attribute(name)
        parent_set = set(parents)
        for p in parent_set:
            if p not in self._parents:
                self.add_attribute(p)
        self._parents.setdefault(name, set()).update(parent_set)
        self._generation += 1

    def add_object(self, ref: str, label: str, attrs: Iterable[str] = ()) -> None:
        """File an object. Same ref filed again → intent union (dedup by
        content address, SPEC §3); the latest non-empty label wins."""
        attr_set = frozenset(attrs)
        for a in attr_set:
            validate_attribute(a)
            if a not in self._parents:
                raise UnknownAttributeError(a)
        if ref in self._objects:
            old_label, old_attrs = self._objects[ref]
            self._objects[ref] = (label or old_label, old_attrs | attr_set)
        else:
            self._objects[ref] = (label, attr_set)
        self._generation += 1

    # ------------------------------------------------------- ConceptIndex

    def closure(self, attrs: Iterable[str]) -> frozenset[str]:
        out: set[str] = set()
        stack = list(attrs)
        for a in stack:
            if a not in self._parents:
                raise UnknownAttributeError(a)
        while stack:
            a = stack.pop()
            if a in out:
                continue
            out.add(a)
            stack.extend(self._parents[a])
        return frozenset(out)

    def _closed_intent(self, ref: str) -> frozenset[str]:
        return self.closure(self._objects[ref][1])

    def _info(self, ref: str) -> ObjectInfo:
        label, _ = self._objects[ref]
        return ObjectInfo(ref=ref, label=label, intent=self._closed_intent(ref))

    def _extent_refs(self, intent: frozenset[str]) -> frozenset[str]:
        return frozenset(
            ref
            for ref, (_, attrs) in self._objects.items()
            if attrs and intent <= self.closure(attrs)
        )

    @staticmethod
    def _sorted(infos: Iterable[ObjectInfo]) -> tuple[ObjectInfo, ...]:
        return tuple(sorted(infos, key=lambda o: (o.label, o.ref)))

    def extent(self, intent: frozenset[str]) -> tuple[ObjectInfo, ...]:
        return self._sorted(self._info(r) for r in self._extent_refs(intent))

    def objects_at(self, intent: frozenset[str]) -> tuple[ObjectInfo, ...]:
        return self._sorted(
            self._info(ref)
            for ref, (_, attrs) in self._objects.items()
            if attrs and self.closure(attrs) == intent
        )

    def children(self, intent: frozenset[str]) -> frozenset[str]:
        current = self._extent_refs(intent)
        if not current:
            return frozenset()
        candidates: dict[str, frozenset[str]] = {}
        for a in self._parents:
            if a in intent:
                continue
            ext = self._extent_refs(self.closure(intent | {a}))
            if ext and ext != current:
                candidates[a] = ext
        return frozenset(
            a
            for a, ext in candidates.items()
            if not any(ext < other for other in candidates.values())
        )

    def unfiled(self) -> tuple[ObjectInfo, ...]:
        return self._sorted(
            ObjectInfo(ref=ref, label=label, intent=frozenset())
            for ref, (label, attrs) in self._objects.items()
            if not attrs
        )

    def get_object(self, ref: str) -> ObjectInfo | None:
        if ref not in self._objects:
            return None
        label, attrs = self._objects[ref]
        if not attrs:
            return ObjectInfo(ref=ref, label=label, intent=frozenset())
        return self._info(ref)

    def generation(self) -> int:
        return self._generation
