"""Parametric dimensions through the filesystem (ontodag >= 0.10.1).

Per ROADMAP § "Upstream: ontodag dimension lattices": parametric path
components are single attribute constraints (concatenation stays AND, hard
rule 3 intact), a well-formed term of a declared dimension is a *virtual*
directory needing no node, sugar resolves to the canonical name on lookup,
listings show present values only, and malformed parameters are
FileNotFoundError on the read side. OntoDAG-backed index only — the
in-memory index has no DAG to declare dimensions in.

Re-baselined 2026-08-03 for ontodag's registry 3.0/4.0 canonical names. Values
are reduced rationals of the SI anchor, not integers in base units:
`weight(3kg)` is canonical (it used to be `weight(3000000mg)`), `weight(4.5kg)`
canonicalizes to `weight(9/2kg)`, and sub-base precision is exact rather than
refused. The slash that arrives with rationals is a path-component hazard, not
a naming one — see tests/test_names.py and src/ontodag_fs/names.py."""

from types import SimpleNamespace

import pytest
from ontodag.dag import OntoDAG
from swarmfs import SwarmFileSystem

from conftest import FakeSwarmClient, seed
from ontodag_fs import OntoDAGFileSystem, OntoDAGIndex
from ontodag_fs.index import UnknownAttributeError


@pytest.fixture()
def market() -> SimpleNamespace:
    dag = OntoDAG()
    index = OntoDAGIndex(dag)
    for name, parents in {
        "dimension": [], "linear-dimension": ["dimension"],
        "prefix-dimension": ["dimension"],
        "weight": ["linear-dimension"], "geo": ["prefix-dimension"],
        "parcel": [], "document": [],
    }.items():
        index.add_attribute(name, parents)
    store: dict[bytes, bytes] = {}
    refs = {}
    for key, (data, label, attrs) in {
        "light": (b"3kg parcel", "light.txt", {"parcel", "weight(3kg)"}),
        "heavy": (b"9kg parcel", "heavy.txt", {"parcel", "weight(9kg)"}),
        "near": (b"nearby thing", "near.txt", {"parcel", "geo(u2edk)"}),
        "plain": (b"just a doc", "readme.md", {"document"}),
    }.items():
        ref = seed(store, data)
        index.add_object(ref, label, attrs)
        refs[key] = ref
    swarm = SwarmFileSystem(client=FakeSwarmClient(store),
                            skip_instance_cache=True)
    fs = OntoDAGFileSystem(index=index, swarm=swarm)
    return SimpleNamespace(fs=fs, index=index, dag=dag, refs=refs)


class TestVirtualDirectories:
    def test_virtual_term_is_a_directory(self, market):
        # asked for in sugar (grams), so the canonical intent is the interesting
        # part: registry 3.0 reduces to the SI anchor, `..5000g` -> `..5kg`
        assert market.fs.isdir("/parcel/weight(..5000g)")
        info = market.fs.info("/parcel/weight(..5000g)")
        assert info["type"] == "directory"
        assert "weight(..5kg)" in info["intent"]         # canonical intent
        # ... and asking created nothing:
        assert "weight(..5kg)" not in market.dag.nodes

    def test_virtual_dir_contents(self, market):
        names = {e.rsplit("/", 1)[-1]
                 for e in market.fs.ls("/parcel/weight(..5kg)/.all")}
        assert "light.txt" in names
        assert "heavy.txt" not in names

    def test_empty_virtual_dir_still_exists(self, market):
        assert market.fs.isdir("/weight(100kg..)")
        assert market.fs.ls("/weight(100kg..)/.all") == []

    def test_prefix_dimension(self, market):
        names = {e.rsplit("/", 1)[-1] for e in market.fs.ls("/geo(u2)/.all")}
        assert "near.txt" in names
        assert "readme.md" not in names

    def test_order_insensitive_with_parametric_components(self, market):
        a = market.fs.info("/parcel/weight(..5kg)")["intent"]
        b = market.fs.info("/weight(..5kg)/parcel")["intent"]
        assert a == b


class TestSugarAndCanonical:
    def test_sugar_resolves_on_lookup(self, market):
        assert market.fs.info("/weight(3kg)")["intent"] == \
            market.fs.info("/weight(3000g)")["intent"]

    def test_listings_show_present_values_canonically(self, market):
        children = {e.rsplit("/", 1)[-1] for e in market.fs.ls("/weight")
                    if not e.endswith(".all")}
        assert "weight(3kg)" in children
        assert "weight(9kg)" in children
        # present values only — never an enumeration of the value space
        assert len({c for c in children if c.startswith("weight(")}) == 2

    def test_head_is_implied_by_the_term(self, market):
        # /weight/weight(..5kg) ≡ /weight(..5kg): redundancy is harmless
        assert market.fs.info("/weight/weight(..5kg)")["intent"] == \
            market.fs.info("/weight(..5kg)")["intent"]


class TestErrors:
    def test_malformed_parameter_is_file_not_found(self, market):
        assert not market.fs.exists("/weight(3zz)")      # unknown unit
        assert not market.fs.exists("/weight(nonsense)")  # unparseable value
        with pytest.raises(FileNotFoundError):
            market.fs.ls("/weight(nonsense)")

    def test_sub_base_precision_is_exact_not_an_error(self, market):
        """Registry 3.0 made canonical values reduced rationals, so precision
        below the old base unit is exact rather than refused — this used to be
        a boundary error mapped to ENOENT."""
        assert market.fs.isdir("/weight(0.0005g)")
        assert market.index.closure(["weight(0.0005g)"]) >= {
            "weight(1/2000000kg)", "weight",
        }

    def test_undeclared_head_stays_opaque(self, market):
        assert not market.fs.exists("/foo(3kg)")
        market.index.add_attribute("foo(3kg)")   # opaque atom, fileable
        assert market.fs.isdir("/foo(3kg)")

    def test_builder_guards_surface(self, market):
        with pytest.raises(UnknownAttributeError):
            market.index.closure(["bar(1kg..)"])
        with pytest.raises(ValueError):          # ontodag disjoint guard
            market.index.add_object("ab" * 32, "x.txt",
                                    {"weight(..2kg)", "weight(3kg..)"})


class TestFilingUnderSugar:
    def test_add_object_materializes_canonical_value(self, market):
        ref = "cd" * 32
        market.index.add_object(ref, "mid.txt", {"parcel", "weight(4.5kg)"})
        assert "weight(9/2kg)" in market.dag.nodes      # reduced rational
        names = {e.rsplit("/", 1)[-1]
                 for e in market.fs.ls("/parcel/weight(..5kg)/.all")}
        assert "mid.txt" in names

    def test_rational_value_is_reachable_under_its_listed_name(self, market):
        """A canonical name containing '/' is not a path component, so listings
        show it percent-encoded — and the shown name must resolve. Before the
        encoding layer, `ls` emitted an entry its own `isdir` denied."""
        market.index.add_object("cd" * 32, "mid.txt", {"parcel", "weight(4.5kg)"})
        listed = [e for e in market.fs.ls("/parcel/weight")
                  if "weight(" in e.rsplit("/", 1)[-1]]
        assert "/parcel/weight/weight(9%2F2kg)" in listed
        for entry in listed:
            assert market.fs.isdir(entry), entry
        names = {e.rsplit("/", 1)[-1]
                 for e in market.fs.ls("/parcel/weight/weight(9%2F2kg)/.all")}
        assert names == {"mid.txt"}
        # the encoded path and the sugar path denote the same concept
        assert market.fs.info("/parcel/weight/weight(9%2F2kg)")["intent"] == \
            market.fs.info("/parcel/weight(4.5kg)")["intent"]
