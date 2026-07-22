"""End-to-end through the real persistence stack: the zoo filed into a
SwarmOntoDAG (recordstore over an in-memory bytes store), committed,
rehydrated from the root, and browsed through OntoDAGFileSystem — the
"DAG on Swarm" configuration, offline."""

from __future__ import annotations

import pytest

recordstore = pytest.importorskip("recordstore")

from ontodag.swarm_adapter import SwarmOntoDAG
from recordstore import MemoryBytesStore, RecordStore
from swarmfs import SwarmFileSystem

from ontodag_fs import OntoDAGFileSystem, OntoDAGIndex

from conftest import ATTRIBUTES, OBJECTS, FakeSwarmClient, seed


def test_zoo_survives_commit_and_rehydrate():
    blobs = MemoryBytesStore()
    store: dict[bytes, bytes] = {}

    dag = SwarmOntoDAG(RecordStore(blobs))
    index = OntoDAGIndex(dag)
    for name, parents in ATTRIBUTES.items():
        index.add_attribute(name, parents)
    refs = {}
    for key, (data, label, attrs) in OBJECTS.items():
        ref = seed(store, data)
        index.add_object(ref, label, attrs)
        refs[key] = ref
    root = dag.commit()

    # a fresh process: hydrate from the committed root, mount, browse
    again = SwarmOntoDAG(RecordStore.at(root, blobs))
    fs = OntoDAGFileSystem(
        index=OntoDAGIndex(again),
        swarm=SwarmFileSystem(client=FakeSwarmClient(store), skip_instance_cache=True),
    )
    assert fs.cat_file("/pet/mammal/dog/rex.jpg") == b"rex the dog"
    assert fs.info("/dog")["intent"] == ["animal", "dog", "mammal", "pet"]
    assert fs.info("/dog/rex.jpg")["label"] == "rex.jpg"
    assert [e.rsplit("/", 1)[-1] for e in fs.ls("/.unfiled")] == ["orphan.bin"]
    all_refs = {e["swarm_ref"] for e in fs.ls("/.all", detail=True)}
    assert all_refs == {refs[k] for k in refs if k != "orphan"}
