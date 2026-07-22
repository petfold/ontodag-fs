"""info/exists/isdir/isfile/checksum semantics, incl. the dual-nature rule."""

from __future__ import annotations

import pytest
from swarmfs import SwarmFileSystem

from ontodag_fs import InMemoryIndex, OntoDAGFileSystem

from conftest import FakeSwarmClient, seed


def test_directory_info_carries_closed_intent(zoo):
    info = zoo.fs.info("/pet/dog")
    assert info["type"] == "directory"
    # dog implies mammal, pet, animal
    assert info["intent"] == ["animal", "dog", "mammal", "pet"]


def test_file_info_size_ref_intent(zoo):
    info = zoo.fs.info("/dog/rex.jpg")
    assert info["type"] == "file"
    assert info["size"] == len(b"rex the dog")
    assert info["swarm_ref"] == zoo.refs["rex"]
    assert info["intent"] == ["animal", "dog", "mammal", "pet"]
    assert info["label"] == "rex.jpg"


def test_checksum_is_the_swarm_reference(zoo):
    assert zoo.fs.checksum("/dog/rex.jpg") == zoo.refs["rex"]
    with pytest.raises(IsADirectoryError):
        zoo.fs.checksum("/pet/dog")


def test_exists(zoo):
    assert zoo.fs.exists("/")
    assert zoo.fs.exists("/pet/dog")
    assert zoo.fs.exists("/dog/pet")  # order-insensitive
    assert zoo.fs.exists("/pet/dog/rex.jpg")
    assert not zoo.fs.exists("/pet/unicorn")
    assert not zoo.fs.exists("/pet/dog/ghost.txt")


def test_isdir_isfile_basics(zoo):
    assert zoo.fs.isdir("/pet/dog")
    assert not zoo.fs.isfile("/pet/dog")
    assert zoo.fs.isfile("/pet/dog/rex.jpg")
    assert not zoo.fs.isdir("/pet/dog/rex.jpg")
    assert zoo.fs.isdir("/pet/.all")
    assert zoo.fs.isdir("/.unfiled")


def dual_nature_fixture():
    """An index where the name 'wolf' is both an attribute and a label."""
    store: dict[bytes, bytes] = {}
    idx = InMemoryIndex()
    idx.add_attribute("mammal")
    idx.add_attribute("wolf", ["mammal"])
    wolf_obj = seed(store, b"a wolf portrait")
    pack = seed(store, b"the pack")
    idx.add_object(wolf_obj, "wolf", {"mammal"})   # label collides with attr
    idx.add_object(pack, "pack.txt", {"wolf"})
    swarm = SwarmFileSystem(client=FakeSwarmClient(store), skip_instance_cache=True)
    return OntoDAGFileSystem(index=idx, swarm=swarm), wolf_obj


def test_dual_nature_attribute_wins_isdir_object_wins_isfile():
    fs, wolf_ref = dual_nature_fixture()
    names = fs.ls("/mammal", detail=True)
    types = {(e["name"], e["type"]) for e in names}
    assert ("/mammal/wolf", "directory") in types
    assert ("/mammal/wolf", "file") in types
    assert fs.isdir("/mammal/wolf")
    assert fs.isfile("/mammal/wolf")
    assert fs.info("/mammal/wolf")["type"] == "directory"  # attribute wins
    assert fs.cat_file("/mammal/wolf") == b"a wolf portrait"  # object wins
    assert fs.checksum("/mammal/wolf") == wolf_ref
