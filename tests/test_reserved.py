"""Reserved namespaces: /.swarm/ read-through and /.unfiled/ (SPEC §2)."""

from __future__ import annotations

import pytest

from conftest import seed


def test_swarm_raw_read_through(zoo):
    ref = zoo.refs["rex"]
    path = f"/.swarm/{ref}"
    assert zoo.fs.exists(path)
    assert zoo.fs.isfile(path)
    assert not zoo.fs.isdir(path)
    info = zoo.fs.info(path)
    assert info["type"] == "file"
    assert info["size"] == len(b"rex the dog")
    assert zoo.fs.cat_file(path) == b"rex the dog"
    assert zoo.fs.checksum(path) == ref


def test_swarm_read_works_for_unclassified_content(zoo):
    # content that OntoDAG has never heard of is still readable by address
    ref = seed(zoo.store, b"never filed")
    assert zoo.fs.cat_file(f"/.swarm/{ref}") == b"never filed"


def test_swarm_namespace_is_not_enumerable(zoo):
    assert zoo.fs.ls("/.swarm") == []
    assert zoo.fs.isdir("/.swarm")


def test_swarm_bad_or_missing_ref_is_enoent(zoo):
    with pytest.raises(FileNotFoundError):
        zoo.fs.cat_file("/.swarm/not-a-reference")
    absent = "ab" * 32
    assert not zoo.fs.exists(f"/.swarm/{absent}")
    with pytest.raises(FileNotFoundError):
        zoo.fs.cat_file(f"/.swarm/{absent}")


def test_unfiled_holds_empty_intent_objects(zoo):
    entries = zoo.fs.ls("/.unfiled", detail=True)
    assert [e["name"] for e in entries] == ["/.unfiled/orphan.bin"]
    assert zoo.fs.cat_file("/.unfiled/orphan.bin") == b"orphan bytes"
    assert zoo.fs.info("/.unfiled/orphan.bin")["size"] == len(b"orphan bytes")


def test_unfiled_objects_do_not_leak_into_concept_extents(zoo):
    all_refs = {e["swarm_ref"] for e in zoo.fs.ls("/.all", detail=True)}
    assert zoo.refs["orphan"] not in all_refs


def test_range_reads(zoo):
    assert zoo.fs.cat_file("/wolf/pack.txt", start=0, end=4) == b"wolf"
    with zoo.fs.open("/wolf/pack.txt") as f:
        assert f.read(4) == b"wolf"
        assert f.read() == b" pack"
