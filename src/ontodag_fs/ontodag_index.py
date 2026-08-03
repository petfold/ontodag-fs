"""ConceptIndex over a real OntoDAG (decisions #12/#13).

Objects are leaf Items whose *name is the Swarm reference*, marked by
``metadata["object"] = True`` and carrying the display label in
``metadata["label"]``. Categories are every other non-root node. Closure is
the ancestor set; extents are OntoDAG's descendant-cone intersections
filtered to object nodes.

Works with a plain in-memory ``OntoDAG`` or a persistence-backed
``EagerOntoDAG`` alike — persistence is the DAG's business, never this
layer's. The builder surface (``add_attribute``/``add_object``) matches
``InMemoryIndex`` so the two implementations are drop-in interchangeable
(and are tested against the same suite).
"""

from __future__ import annotations

from typing import Iterable

from ontodag.dag import Item, OntoDAG

from .index import ObjectInfo, UnknownAttributeError
from .memory import validate_attribute

OBJECT_KEY = "object"
LABEL_KEY = "label"


class OntoDAGIndex:
    def __init__(self, dag: OntoDAG) -> None:
        self._dag = dag
        # Bumped by mutations through this layer; out-of-band DAG edits are
        # caught by the filesystem cache's TTL (SPEC §4).
        self._generation = 0

    # ---------------------------------------------------------- dimensions
    #
    # Parametric terms (weight(..5kg), geo(u2ed)) are single attribute
    # constraints whose subsumption is computed from the name —
    # ROADMAP § "Upstream: ontodag dimension lattices". A term of a declared
    # dimension is a valid attribute even when no node exists (a VIRTUAL
    # directory: infinite namespace, computed on demand — lazy
    # materialization is already the house rule). Sugar resolves to the
    # canonical name on lookup (weight(3000g) -> weight(3kg)); listings
    # only ever show present values, because `children` reads them from
    # member intents. Only this OntoDAG-backed index supports dimensions;
    # InMemoryIndex has no DAG to declare them in.
    #
    # Canonical values are reduced rationals of the SI anchor (ontodag
    # registry 3.0/4.0), so weight(4.5kg) canonicalizes to weight(9/2kg) —
    # a name holding a '/'. Nothing here has to care: names.py encodes on the
    # way into a path and decodes on the way out, so the DAG keeps its real
    # names (see SPEC § 2 Naming).

    def _parametric(self, name: str):
        """(head, kind, canonical) for a parametric term of a *declared*
        dimension; None for opaque names. A malformed parameter under a
        declared head is UnknownAttributeError — the filesystem maps it to
        FileNotFoundError, the right read-side answer."""
        # Private upstream API (no public equivalent yet), so probe rather than
        # import: a future ontodag that renames it degrades to opaque names
        # instead of raising AttributeError on every lookup.
        parse = getattr(self._dag, "_parse_parametric", None)
        if parse is None:
            return None
        try:
            return parse(name)
        except ValueError as exc:
            raise UnknownAttributeError(f"{name}: {exc}") from exc

    # ------------------------------------------------------------- building

    def add_attribute(self, name: str, parents: Iterable[str] = ()) -> None:
        validate_attribute(name)
        parent_list = list(parents)
        for p in parent_list:
            if p not in self._dag.nodes:
                self.add_attribute(p)
        self._dag.put(name, parent_list)
        self._generation += 1

    def add_object(self, ref: str, label: str, attrs: Iterable[str] = ()) -> None:
        """File an object. Same ref filed again → intent union (edges are
        additive) and the latest non-empty label wins — identical semantics
        to InMemoryIndex.add_object."""
        attr_list = list(set(attrs))
        for a in attr_list:
            validate_attribute(a)
            node = self._dag.nodes.get(a)
            if node is None or not self._is_category(node):
                # A parametric term of a declared dimension is fileable even
                # unmaterialized: dag.put canonicalizes it, creates the value
                # node and its anchor, and enforces the boundary guards
                # (disjoint parents, unit families) itself.
                if self._parametric(a) is None:
                    raise UnknownAttributeError(a)
        metadata = {OBJECT_KEY: True}
        if label:
            metadata[LABEL_KEY] = label
        self._dag.put(Item(ref, metadata=metadata), attr_list)
        self._generation += 1

    # ------------------------------------------------------- classification

    def _is_object(self, node) -> bool:
        return bool(node.metadata.get(OBJECT_KEY))

    def _is_category(self, node) -> bool:
        return node is not self._dag.root and not self._is_object(node)

    def _object_intent(self, node) -> frozenset[str]:
        return frozenset(
            a.name
            for a in self._dag.get_ancestors(node, ignore={self._dag.root})
        )

    def _info(self, node) -> ObjectInfo:
        return ObjectInfo(
            ref=node.name,
            label=node.metadata.get(LABEL_KEY, node.name),
            intent=self._object_intent(node),
        )

    def _extent_nodes(self, intent: frozenset[str]) -> set:
        if intent:
            below = self._dag.get(sorted(intent))
            return {n for n in below if self._is_object(n)}
        # top concept: every *filed* object; unfiled (root-only parents)
        # objects live under /.unfiled exclusively
        return {
            n
            for n in self._dag.nodes.values()
            if self._is_object(n) and self._object_intent(n)
        }

    @staticmethod
    def _sorted(infos: Iterable[ObjectInfo]) -> tuple[ObjectInfo, ...]:
        return tuple(sorted(infos, key=lambda o: (o.label, o.ref)))

    # --------------------------------------------------------- ConceptIndex

    def closure(self, attrs: Iterable[str]) -> frozenset[str]:
        out: set[str] = set()
        for a in set(attrs):
            node = self._dag.nodes.get(a)
            if node is None or not self._is_category(node):
                parsed = self._parametric(a)
                if parsed is None:
                    raise UnknownAttributeError(a)
                head, _kind, canonical = parsed
                out.add(canonical)
                node = self._dag.nodes.get(canonical)
                if node is None:
                    # Virtual term: no node, but its head chain is still
                    # implied — /weight/weight(..5kg) ≡ /weight(..5kg).
                    node = self._dag.nodes[head]
            out.add(node.name)
            out.update(
                anc.name
                for anc in self._dag.get_ancestors(node, ignore={self._dag.root})
            )
        return frozenset(out)

    def extent(self, intent: frozenset[str]) -> tuple[ObjectInfo, ...]:
        return self._sorted(self._info(n) for n in self._extent_nodes(frozenset(intent)))

    def objects_at(self, intent: frozenset[str]) -> tuple[ObjectInfo, ...]:
        intent = frozenset(intent)
        return self._sorted(
            info
            for info in (self._info(n) for n in self._extent_nodes(intent))
            if info.intent == intent
        )

    def children(self, intent: frozenset[str]) -> frozenset[str]:
        intent = frozenset(intent)
        members = self._extent_nodes(intent)
        if not members:
            return frozenset()
        current = {n.name for n in members}
        # only attributes present in some member's intent can refine
        candidate_attrs = set().union(
            *(self._object_intent(n) for n in members)
        ) - intent
        candidates: dict[str, frozenset[str]] = {}
        for a in candidate_attrs:
            ext = frozenset(
                n.name for n in self._extent_nodes(self.closure(intent | {a}))
            )
            if ext and ext != current:
                candidates[a] = ext
        return frozenset(
            a
            for a, ext in candidates.items()
            if not any(ext < other for other in candidates.values())
        )

    def unfiled(self) -> tuple[ObjectInfo, ...]:
        return self._sorted(
            ObjectInfo(
                ref=n.name,
                label=n.metadata.get(LABEL_KEY, n.name),
                intent=frozenset(),
            )
            for n in self._dag.nodes.values()
            if self._is_object(n) and not self._object_intent(n)
        )

    def get_object(self, ref: str) -> ObjectInfo | None:
        node = self._dag.nodes.get(ref)
        if node is None or not self._is_object(node):
            return None
        return self._info(node)

    def generation(self) -> int:
        return self._generation
