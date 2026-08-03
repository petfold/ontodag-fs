"""Every surface a name flows out through here, against one nasty corpus.

The sibling of ontodag's `tests/test_name_consumers.py`, and written for the
same reason. ontodag's 0.10.1 post-mortem concluded that the canonical-name
grammar fans out into consumers with their own escaping rules, and that a
change to the grammar is therefore a cross-cutting change. ontodag-fs is one of
those consumers and was not on the list: registry 3.0 put a `/` into canonical
value names (`weight(4.5kg)` -> `weight(9/2kg)`), and a `/` is the one character
a POSIX path component cannot hold. `ls` went on emitting a directory entry
that its own `isdir` and `ls` denied — a listing that lies.

This file is that fan-out written down on the filesystem side. The consumers a
name reaches here:

    ls (directory entries) · info · isdir/isfile/exists · cat/open ·
    /.all/ (flattened extents) · /.unfiled/ · the `~shorthash` disambiguator

The invariant every one of them owes: **a name that appears in a listing
resolves.** Whatever the grammar puts in a name, `ls` and `info` must agree.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from ontodag.dag import OntoDAG
from swarmfs import SwarmFileSystem

from conftest import FakeSwarmClient, seed
from ontodag_fs import OntoDAGFileSystem, OntoDAGIndex
from ontodag_fs.names import decode_component, encode_component

# Names a user may legally create. ontodag's corpus, plus the two hazards that
# are specific to a *filesystem*: the separator itself, and a string that
# already looks percent-encoded (so decoding must not be a second guess at
# what the user meant).
NASTY_NAMES = {
    "plain": "plain",
    "space": "with space",
    "plus": "C++ notes",
    "ampersand": "a&b",
    "hash": "a#b",
    "pipe": "a|b",                       # the union separator
    "comma": "a,b",                      # the conjunction separator
    "colon": "colon:name",               # the DOT port separator (ontodag)
    "quote": 'quote"q',
    "backslash": "back\\slash",
    "unicode": "unicode-café",
    "leading-dash": "-dash",
    "equals": "a=b",
    "percent": "a%20b",                  # already-encoded-looking
    "percent-triplet": "a%2Fb",          # the ambiguity case, spelled out
    "tilde": "tilde~name",               # the disambiguation separator
}

# Attribute names are validated path-clean (SPEC §1), so a literal '/' can only
# reach the filesystem as a *label* or as a name ontodag computed for itself.
SLASHED_LABELS = {"slash": "a/b.txt", "slash-deep": "x/y/z.txt"}

# Canonical names the system generates. Nobody types these, which is exactly
# why no hand-written fixture contained one when 0.10.0 shipped.
DECLARATIONS = {
    "dimension": [],
    "linear-dimension": ["dimension"],
    "calendar-dimension": ["dimension"],
    "weight": ["linear-dimension"],
    "time": ["calendar-dimension"],
}
# (asserted sugar, canonical name ontodag stores)
GENERATED = [
    ("weight(4.5kg)", "weight(9/2kg)"),        # reduced rational: holds a '/'
    ("weight(3kg)", "weight(3kg)"),
    ("weight(0.0005g)", "weight(1/2000000kg)"),
    ("time(2026-08-15)",
     "time(2026-08-15T00:00:00Z..2026-08-15T23:59:59Z)"),  # holds ':'
]


@pytest.fixture()
def corpus() -> SimpleNamespace:
    """One filesystem holding every name in the corpus."""
    dag = OntoDAG()
    index = OntoDAGIndex(dag)
    for name, parents in DECLARATIONS.items():
        index.add_attribute(name, parents)
    index.add_attribute("parent")
    for name in NASTY_NAMES.values():
        index.add_attribute(name, ["parent"])

    store: dict[bytes, bytes] = {}
    objects = {}
    # one object per nasty attribute, so each attribute has a non-empty extent
    for key, attr in NASTY_NAMES.items():
        ref = seed(store, f"body of {key}".encode())
        index.add_object(ref, f"{key}.txt", {attr})
        objects[key] = ref
    # objects whose *labels* are nasty, filed under a plain attribute
    for key, label in SLASHED_LABELS.items():
        ref = seed(store, f"body of {label}".encode())
        index.add_object(ref, label, {"parent"})
        objects[key] = ref
    # objects under generated canonical names
    for sugar, _canonical in GENERATED:
        ref = seed(store, f"body of {sugar}".encode())
        index.add_object(ref, f"gen-{sugar}.txt", {"parent", sugar})
        objects[sugar] = ref

    fs = OntoDAGFileSystem(
        index=index,
        swarm=SwarmFileSystem(client=FakeSwarmClient(store),
                              skip_instance_cache=True),
    )
    return SimpleNamespace(fs=fs, index=index, dag=dag, store=store,
                           objects=objects)


# ------------------------------------------------------------- the mapping


class TestEncoding:
    @pytest.mark.parametrize("name", sorted(
        list(NASTY_NAMES.values()) + list(SLASHED_LABELS.values())
        + [c for _s, c in GENERATED]
    ))
    def test_round_trip(self, name):
        assert decode_component(encode_component(name)) == name

    @pytest.mark.parametrize("name", sorted(
        list(NASTY_NAMES.values()) + list(SLASHED_LABELS.values())
        + [c for _s, c in GENERATED]
    ))
    def test_encoded_form_is_one_path_component(self, name):
        encoded = encode_component(name)
        assert "/" not in encoded
        assert "\x00" not in encoded
        assert encoded  # never empty

    def test_names_without_hazards_are_untouched(self):
        """No path that resolved before the encoding layer resolves
        differently now."""
        for name in ["plain", "with space", "weight(3kg)", "geo(u2ed)",
                     "time(2026-01-01T00:00:00Z..2026-12-31T23:59:59Z)"]:
            assert encode_component(name) == name
            assert decode_component(name) == name

    @settings(max_examples=300, deadline=None)
    @given(st.text())
    def test_round_trip_is_a_law(self, name):
        assert decode_component(encode_component(name)) == name

    @settings(max_examples=300, deadline=None)
    @given(st.text(), st.text())
    def test_encoding_is_injective(self, one, other):
        """Two different names never encode to the same component — otherwise a
        listing could not be resolved back to one concept. (Follows from the
        round-trip law, and is the property a listing actually depends on.)"""
        if one == other:
            return
        assert encode_component(one) != encode_component(other)


# --------------------------------------------------- the listing invariant


class TestEveryListedNameResolves:
    """The invariant the 0.10.0 fan-out broke: what `ls` shows, `ls` can open."""

    def _walk(self, fs, path="/", depth=0):
        """Every entry reachable by following listings, breadth-limited."""
        entries = fs.ls(path, detail=True)
        for e in entries:
            yield path, e
            if e["type"] == "directory" and depth < 2:
                base = e["name"].rsplit("/", 1)[-1]
                if base in (".swarm", ".unfiled"):
                    continue      # separate namespaces, covered below
                yield from self._walk(fs, e["name"], depth + 1)

    def test_every_directory_entry_is_a_directory(self, corpus):
        seen = 0
        for parent, e in self._walk(corpus.fs):
            if e["type"] != "directory":
                continue
            assert corpus.fs.isdir(e["name"]), f"{e['name']} (listed in {parent})"
            assert corpus.fs.exists(e["name"]), f"{e['name']} (listed in {parent})"
            assert corpus.fs.info(e["name"])["type"] == "directory"
            seen += 1
        assert seen > len(NASTY_NAMES)   # the walk actually covered the corpus

    def test_every_file_entry_is_readable(self, corpus):
        seen = 0
        for parent, e in self._walk(corpus.fs):
            if e["type"] != "file":
                continue
            assert corpus.fs.isfile(e["name"]), f"{e['name']} (listed in {parent})"
            assert corpus.fs.cat_file(e["name"]) == \
                corpus.store[bytes.fromhex(e["swarm_ref"])]
            seen += 1
        assert seen >= len(NASTY_NAMES)

    def test_nasty_attribute_is_browsable_by_its_shown_name(self, corpus):
        listed = {e.rsplit("/", 1)[-1] for e in corpus.fs.ls("/parent")}
        for key, attr in NASTY_NAMES.items():
            shown = encode_component(attr)
            assert shown in listed, key
            assert corpus.fs.isdir(f"/parent/{shown}"), key
            # and the intent carries the *raw* DAG name, not the shown one
            assert attr in corpus.fs.info(f"/parent/{shown}")["intent"], key

    def test_slashed_label_is_readable_by_its_shown_name(self, corpus):
        """A label may hold a '/' — it is display metadata, never validated
        (hard rule 1). It still has to survive being a directory entry."""
        listed = {e.rsplit("/", 1)[-1]
                  for e in corpus.fs.ls("/parent/.all")}
        for key, label in SLASHED_LABELS.items():
            shown = encode_component(label)
            assert shown in listed, key
            assert "/" not in shown
            path = f"/parent/.all/{shown}"
            assert corpus.fs.isfile(path), key
            assert corpus.fs.cat_file(path) == f"body of {label}".encode()
            assert corpus.fs.info(path)["label"] == label   # raw in the data

    @pytest.mark.parametrize("sugar,canonical", GENERATED)
    def test_generated_canonical_name_resolves(self, corpus, sugar, canonical):
        assert canonical in corpus.dag.nodes
        shown = encode_component(canonical)
        assert corpus.fs.isdir(f"/parent/{shown}")
        assert corpus.fs.info(f"/parent/{shown}")["intent"] == \
            corpus.fs.info(f"/parent/{sugar}")["intent"]

    def test_unfiled_listing_resolves(self, corpus):
        ref = seed(corpus.store, b"nobody filed me")
        corpus.index.add_object(ref, "a/b unfiled.txt", ())
        for e in corpus.fs.ls("/.unfiled", detail=True):
            assert corpus.fs.isfile(e["name"]), e["name"]
            assert corpus.fs.cat_file(e["name"]) == \
                corpus.store[bytes.fromhex(e["swarm_ref"])]

    def test_disambiguated_collision_resolves(self, corpus):
        """Two objects sharing a nasty label collide, so both are shown as
        `{stem}~{shorthash}{ext}` — through the encoder as well."""
        for body in (b"first slashed", b"second slashed"):
            corpus.index.add_object(seed(corpus.store, body), "dup/name.txt",
                                    {"parent"})
        shown = [e for e in corpus.fs.ls("/parent/.all", detail=True)
                 if "dup" in e["name"]]
        assert len(shown) == 2
        for e in shown:
            assert "~" in e["name"]
            assert corpus.fs.isfile(e["name"]), e["name"]
            assert corpus.fs.cat_file(e["name"]) == \
                corpus.store[bytes.fromhex(e["swarm_ref"])]


class TestReservedNamesSurviveEncoding:
    def test_dot_names_are_never_encoded(self):
        for reserved in (".all", ".swarm", ".unfiled"):
            assert encode_component(reserved) == reserved

    def test_encoded_dot_is_not_a_way_into_the_reserved_namespace(self, corpus):
        # '.' is not in the escape set, so there is no alternate spelling to
        # smuggle a reserved name through; an attribute may not start with '.'
        with pytest.raises(ValueError):
            corpus.index.add_attribute(".sneaky")
