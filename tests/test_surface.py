"""Readable value names in listings — ontodag's surface layer, output half.

Adopted 2026-08-03 (ROADMAP § "Upstream", the display-only layer it had been
deferring). `ontodag.surface.render` is a pure function of the canonical name
*plus the declarations that give it a kind*, so the DAG has to be passed; the
rule that makes it safe here is its own: rendering only ever picks a spelling
the dimensions grammar already accepts. So a rendered name resolves through
`closure()` with no elaboration step on this side — the sugar path already
canonicalizes it. Display changes; identity does not.

The two layers compose in one direction: canonical -> render -> encode -> path
component, and back by decode -> closure. Rendering removes the '/' from most
rationals (`weight(9/2kg)` -> `weight(4500g)`), which is why listings are
usually clean now; it cannot remove all of them (`length(10/33m)` fits no unit
exactly), which is why names.py is still the backstop.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from ontodag.dag import Item, OntoDAG
from swarmfs import SwarmFileSystem

from conftest import FakeSwarmClient, seed
from ontodag_fs import OntoDAGFileSystem, OntoDAGIndex

DECLARATIONS = {
    "dimension": [],
    "linear-dimension": ["dimension"],
    "calendar-dimension": ["dimension"],
    "weight": ["linear-dimension"],
    "length": ["linear-dimension"],
    "time": ["calendar-dimension"],
    "parcel": [],
}

# (asserted sugar, canonical stored name, readable name a listing shows)
VALUES = [
    ("weight(4.5kg)", "weight(9/2kg)", "weight(4500g)"),
    ("weight(9kg)", "weight(9kg)", "weight(9kg)"),
    ("weight(0.0005g)", "weight(1/2000000kg)", "weight(500ug)"),
    ("time(2026-08)",
     "time(2026-08-01T00:00:00Z..2026-08-31T23:59:59Z)", "time(2026-08)"),
    ("time(2027)",
     "time(2027-01-01T00:00:00Z..2027-12-31T23:59:59Z)", "time(2027)"),
    # a second length value, so the irreducible one below has a refining
    # sibling and both surface as directories (the lattice-children rule skips
    # an attribute whose extent equals the parent's — SPEC §2)
    ("length(2m)", "length(2m)", "length(2m)"),
]

# The shaku, exactly 10/33 m: no unit of the family makes it whole, so it
# survives rendering as a rational and the encoder has to carry it. It goes in
# through the DAG rather than the index builder because asserted attribute
# names stay path-clean (DESIGN_DECISIONS #20) — which is not a gap in the
# fixture but how such a value actually arises: irreducible rationals reach a
# store from ontodag's own API (a graph-declared unit, an import, a merge),
# never from someone typing a path. This repo does not edit the lattice.
IRREDUCIBLE = ("length(10/33m)", "length(10/33m)", "length(10/33m)")


def _market(render_names=None) -> SimpleNamespace:
    dag = OntoDAG()
    index = OntoDAGIndex(dag)
    for name, parents in DECLARATIONS.items():
        index.add_attribute(name, parents)
    store: dict[bytes, bytes] = {}
    for i, (sugar, _canonical, _shown) in enumerate(VALUES):
        ref = seed(store, f"body {i}".encode())
        index.add_object(ref, f"obj{i}.txt", {"parcel", sugar})
    ref = seed(store, b"one shaku")
    dag.put(Item(ref, metadata={"object": True, "label": "shaku.txt"}),
            ["parcel", IRREDUCIBLE[1]])
    fs = OntoDAGFileSystem(
        index=index,
        swarm=SwarmFileSystem(client=FakeSwarmClient(store),
                              skip_instance_cache=True),
        render_names=render_names,
    )
    return SimpleNamespace(fs=fs, index=index, dag=dag, store=store)


@pytest.fixture()
def market() -> SimpleNamespace:
    return _market()


def _children(fs, path):
    return {e.rsplit("/", 1)[-1] for e in fs.ls(path) if not e.endswith("/.all")}


class TestRenderedListings:
    @pytest.mark.parametrize("sugar,canonical,shown", VALUES + [IRREDUCIBLE])
    def test_listing_shows_the_readable_name(self, market, sugar, canonical, shown):
        from ontodag_fs.names import encode_component
        head = canonical.split("(")[0]
        assert canonical in market.dag.nodes            # storage is unchanged
        assert encode_component(shown) in _children(market.fs, f"/parcel/{head}")

    @pytest.mark.parametrize("sugar,canonical,shown", VALUES + [IRREDUCIBLE])
    def test_readable_name_resolves_to_the_same_concept(
            self, market, sugar, canonical, shown):
        from ontodag_fs.names import encode_component
        head = canonical.split("(")[0]
        path = f"/parcel/{head}/{encode_component(shown)}"
        assert market.fs.isdir(path)
        # the readable, the canonical and the originally asserted spelling are
        # three names for one concept
        assert market.fs.info(path)["intent"] == \
            market.fs.info(f"/parcel/{encode_component(canonical)}")["intent"]
        assert market.fs.info(path)["intent"] == \
            market.fs.info(f"/parcel/{encode_component(sugar)}")["intent"]

    @pytest.mark.parametrize("sugar,canonical,shown", VALUES + [IRREDUCIBLE])
    def test_intent_stays_canonical(self, market, sugar, canonical, shown):
        """Rendering is display-only: what a listing *shows* changes, what the
        entry *reports* does not. Intents are data and must never be rendered,
        or they would stop matching the DAG."""
        from ontodag_fs.names import encode_component
        head = canonical.split("(")[0]
        intent = market.fs.info(f"/parcel/{head}/{encode_component(shown)}")["intent"]
        assert canonical in intent
        if shown != canonical:
            assert shown not in intent

    def test_timestamps_are_no_longer_shown_as_ranges(self, market):
        shown = _children(market.fs, "/parcel/time")
        assert shown == {"time(2026-08)", "time(2027)"}
        assert not any("T00:00:00Z" in s for s in shown)

    def test_most_rationals_no_longer_need_encoding(self, market):
        """The point of adopting render: `weight(9/2kg)` reaches the user as
        `weight(4500g)`, so the %2F escape becomes rare rather than routine."""
        shown = _children(market.fs, "/parcel/weight")
        assert "weight(4500g)" in shown
        assert not any("%2F" in s for s in shown)

    def test_the_irreducible_rational_still_gets_encoded(self, market):
        """...but not extinct: 10/33 m is exact in no unit, so the two layers
        have to compose."""
        shown = _children(market.fs, "/parcel/length")
        assert shown == {"length(10%2F33m)", "length(2m)"}
        assert market.fs.isdir("/parcel/length/length(10%2F33m)")

    def test_opaque_names_are_untouched(self, market):
        """Dimension heads and ordinary categories are not parametric, so
        rendering leaves them exactly as they are."""
        heads = _children(market.fs, "/parcel")
        assert heads and all("(" not in c for c in heads)
        assert all(market.index.display_name(c) == c for c in heads)


class TestTheHonestSwitch:
    """ontodag's SURFACE_LAYER.md §7: "one tool with an honest switch"."""

    def test_raw_listings_show_canonical_names(self):
        market = _market(render_names=False)
        assert _children(market.fs, "/parcel/weight") == {
            "weight(9%2F2kg)", "weight(9kg)", "weight(1%2F2000000kg)",
        }
        assert _children(market.fs, "/parcel/time") == {
            "time(2026-08-01T00:00:00Z..2026-08-31T23:59:59Z)",
            "time(2027-01-01T00:00:00Z..2027-12-31T23:59:59Z)",
        }

    def test_raw_names_still_resolve(self):
        market = _market(render_names=False)
        for entry in market.fs.ls("/parcel/weight"):
            assert market.fs.isdir(entry), entry

    def test_env_var_turns_rendering_off(self, monkeypatch):
        monkeypatch.setenv("ONTODAG_SURFACE", "0")
        assert "weight(9%2F2kg)" in _children(_market().fs, "/parcel/weight")

    def test_env_var_auto_means_on(self, monkeypatch):
        monkeypatch.setenv("ONTODAG_SURFACE", "auto")
        assert "weight(4500g)" in _children(_market().fs, "/parcel/weight")

    def test_explicit_argument_beats_the_environment(self, monkeypatch):
        monkeypatch.setenv("ONTODAG_SURFACE", "0")
        market = _market(render_names=True)
        assert "weight(4500g)" in _children(market.fs, "/parcel/weight")


class TestBothSpellingsAlwaysWork:
    """Whichever way the switch is set, every spelling of a value resolves —
    the switch changes what is *shown*, never what is *accepted*."""

    @pytest.mark.parametrize("render_names", [True, False])
    @pytest.mark.parametrize("sugar,canonical,shown", VALUES + [IRREDUCIBLE])
    def test_all_three_spellings_resolve(
            self, render_names, sugar, canonical, shown):
        from ontodag_fs.names import encode_component
        market = _market(render_names=render_names)
        intents = {
            spelling: market.fs.info(f"/parcel/{encode_component(spelling)}")["intent"]
            for spelling in (sugar, canonical, shown)
        }
        assert len(set(map(frozenset, intents.values()))) == 1, intents


class TestIndexSeam:
    def test_in_memory_index_renders_to_identity(self):
        """The Protocol's display_name is identity where there is no surface
        layer, so the two implementations stay drop-in interchangeable."""
        from ontodag_fs import InMemoryIndex
        index = InMemoryIndex()
        for name in ("dog", "pet", "weight(3kg)"):
            assert index.display_name(name) == name

    def test_ontodag_index_renders(self, market):
        assert market.index.display_name("weight(9/2kg)") == "weight(4500g)"
        assert market.index.display_name("parcel") == "parcel"

    def test_render_failure_degrades_to_the_canonical_name(self, market,
                                                           monkeypatch):
        """Display must never be able to make a directory unlistable."""
        import ontodag_fs.ontodag_index as mod

        def boom(*a, **k):
            raise RuntimeError("surface exploded")

        monkeypatch.setattr(mod._surface, "render", boom)
        assert market.index.display_name("weight(9/2kg)") == "weight(9/2kg)"
        assert market.fs.ls("/parcel/weight")   # still lists
