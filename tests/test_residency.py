"""The filesystem must not care how much of the DAG is resident.

ontodag offers three residencies over the same committed root: `EagerOntoDAG`
hydrates the whole store, `LazyOntoDAG` fetches nodes as a query walks them,
and `SparseOntoDAG` adds partially-resident writes on top of the lazy reader.
A mount over a large published store wants the lazy end — the fs layer is
already lazy (hard rule 5), and loading the whole lattice to answer `ls /pet`
is the one eager step left in the stack.

Evaluated 2026-08-03. The browse path worked over `LazyOntoDAG` unchanged, but
two places in `OntoDAGIndex` read `self._dag.nodes.values()`, and on a lazy DAG
that dict holds only what has been fetched so far. They did not raise — they
answered with whatever happened to be cached, so `ls /` reported 4 of 60
children and `/.unfiled` reported none of two objects, and the answer changed
depending on which query ran first. Silent, order-dependent wrongness is the
worst failure mode available, so both now walk the DAG instead:

    top concept  -> dag.get([])        (ontodag's empty-query-is-the-universe)
    unfiled      -> dag.root.neighbors (unfiled objects hang off the root)

These tests are the guard. They compare answers across residencies rather than
asserting fixed values, so they keep holding as the fixture changes — and they
run the lazy DAG *fresh* for each operation, because a lazy DAG that has
already served one query is no longer a test of laziness.
"""

from __future__ import annotations

import pytest
from ontodag.dag import Item
from ontodag.eager import EagerOntoDAG
from ontodag.lazy import LazyOntoDAG, SparseOntoDAG
from recordstore import MemoryBytesStore, RecordStore
from swarmfs import SwarmFileSystem

from conftest import FakeSwarmClient, seed
from ontodag_fs import OntoDAGFileSystem, OntoDAGIndex

N_ATTRS = 12
N_OBJECTS = 24
N_LOOSE = 2


@pytest.fixture(scope="module")
def published():
    """One committed root plus the bytes its objects refer to."""
    blobs = MemoryBytesStore()
    dag = EagerOntoDAG(RecordStore(blobs))
    store: dict[bytes, bytes] = {}
    dag.put("thing", [])
    for i in range(N_ATTRS):
        dag.put(f"attr{i:02d}", ["thing"])
    for name, parents in (("dimension", []), ("linear-dimension", ["dimension"]),
                          ("weight", ["linear-dimension"])):
        dag.put(name, parents)
    for i in range(N_OBJECTS):
        ref = seed(store, f"body {i}".encode())
        attrs = [f"attr{i % N_ATTRS:02d}", f"attr{(i * 5) % N_ATTRS:02d}"]
        if i % 6 == 0:
            attrs.append(f"weight({i + 1}kg)")
        dag.put(Item(ref, metadata={"object": True, "label": f"obj{i:03d}.txt"}),
                attrs)
    for i in range(N_LOOSE):
        ref = seed(store, f"loose {i}".encode())
        dag.put(Item(ref, metadata={"object": True, "label": f"loose{i}.txt"}), [])
    root = dag.commit()
    return {"root": root, "blobs": blobs, "store": store}


def _fs(published, residency):
    """A filesystem over the published root at the given residency. Always a
    fresh DAG: residency is only meaningful before anything has been fetched."""
    rs = RecordStore.at(published["root"], published["blobs"])
    dag = {
        "eager": EagerOntoDAG,
        "lazy": LazyOntoDAG,
        "sparse": SparseOntoDAG,
    }[residency](rs)
    return OntoDAGFileSystem(
        index=OntoDAGIndex(dag),
        swarm=SwarmFileSystem(client=FakeSwarmClient(published["store"]),
                              skip_instance_cache=True),
    )


def _names(fs, path):
    return sorted(e.rsplit("/", 1)[-1] for e in fs.ls(path))


# Every operation whose answer must not depend on residency. Each is a
# (label, callable) pair run against a filesystem.
OPERATIONS = {
    "ls /": lambda fs: _names(fs, "/"),
    "ls / detail types": lambda fs: sorted(
        (e["name"], e["type"]) for e in fs.ls("/", detail=True)),
    "ls /.unfiled": lambda fs: _names(fs, "/.unfiled"),
    "ls /thing": lambda fs: _names(fs, "/thing"),
    "ls /thing/.all": lambda fs: _names(fs, "/thing/.all"),
    "ls /attr03": lambda fs: _names(fs, "/attr03"),
    "ls /attr03/.all": lambda fs: _names(fs, "/attr03/.all"),
    "ls /weight": lambda fs: _names(fs, "/weight"),
    "ls virtual value dir": lambda fs: _names(fs, "/weight(..50kg)/.all"),
    "isdir virtual": lambda fs: fs.isdir("/weight(..50kg)"),
    "info /attr03 intent": lambda fs: fs.info("/attr03")["intent"],
    "cat one file": lambda fs: fs.cat_file("/attr00/.all/obj000.txt"),
}


@pytest.fixture(scope="module")
def reference(published):
    """The eager answers — the definition of correct."""
    fs = _fs(published, "eager")
    return {label: op(fs) for label, op in OPERATIONS.items()}


@pytest.mark.parametrize("residency", ["lazy", "sparse"])
@pytest.mark.parametrize("label", sorted(OPERATIONS))
def test_answer_is_independent_of_residency(published, reference, residency, label):
    fs = _fs(published, residency)          # fresh: nothing fetched yet
    assert OPERATIONS[label](fs) == reference[label]


@pytest.mark.parametrize("residency", ["eager", "lazy", "sparse"])
def test_unfiled_is_found_without_a_full_scan(published, residency):
    """The regression that started this: `/.unfiled` read every node, so on a
    lazy DAG it returned nothing at all."""
    fs = _fs(published, residency)
    assert _names(fs, "/.unfiled") == [f"loose{i}.txt" for i in range(N_LOOSE)]


@pytest.mark.parametrize("residency", ["eager", "lazy", "sparse"])
def test_top_concept_sees_every_filed_object(published, residency):
    """...and `ls /` reported a fraction of the lattice."""
    fs = _fs(published, residency)
    everything = _names(fs, "/thing/.all")
    assert len(everything) == N_OBJECTS
    # the top concept's own extent agrees, and excludes the unfiled ones
    top = _names(fs, "/.all")
    assert len(top) == N_OBJECTS
    assert not any(n.startswith("loose") for n in top)


def test_a_lazy_dag_really_starts_cold(published):
    """Guards the guard: if LazyOntoDAG ever hydrated on construction, every
    test above would pass for the wrong reason."""
    dag = LazyOntoDAG(RecordStore.at(published["root"], published["blobs"]))
    resident = sum(1 for n in dag.nodes.values() if n.metadata.get("object"))
    assert resident < N_OBJECTS, (
        "a fresh LazyOntoDAG is already fully resident — these tests would no "
        "longer be testing partial residency"
    )


def test_scanning_nodes_directly_is_still_the_wrong_move(published):
    """Documents *why* the two call sites changed, so the reasoning survives
    even if someone reverts the implementation and wonders why tests fail."""
    dag = LazyOntoDAG(RecordStore.at(published["root"], published["blobs"]))
    before = {n.name for n in dag.nodes.values() if n.metadata.get("object")}
    dag.get([])                                     # touch the whole universe
    after = {n.name for n in dag.nodes.values() if n.metadata.get("object")}
    assert len(after) > len(before), (
        "nodes.values() on a lazy DAG answers with whatever is resident; it "
        "grew after a query, which is exactly why it cannot back an extent"
    )
