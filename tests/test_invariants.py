"""Property-based read-side invariants 1, 2, 6, 8 from SPEC §6."""

from __future__ import annotations

import hashlib

import pytest
from hypothesis import given, settings, strategies as st

from conftest import ATTRIBUTES, INDEX_BACKENDS, build_zoo

# read-only tests: shared instances are safe and fast; both index
# implementations must satisfy the same invariants
ZOOS = {backend: build_zoo(backend) for backend in INDEX_BACKENDS}
on_each_backend = pytest.mark.parametrize("backend", INDEX_BACKENDS)

attr_sets = st.sets(st.sampled_from(sorted(ATTRIBUTES)), min_size=1, max_size=4)


def listing_signature(fs, path):
    """(basename, type, swarm_ref) triples — path-prefix-independent."""
    return {
        (e["name"].rsplit("/", 1)[-1], e["type"], e.get("swarm_ref"))
        for e in fs.ls(path, detail=True)
    }


# 1. resolve(p) == resolve(shuffle(p))
@on_each_backend
@given(attrs=attr_sets, data=st.data())
def test_order_insensitivity(backend, attrs, data):
    zoo = ZOOS[backend]
    ordered = sorted(attrs)
    shuffled = data.draw(st.permutations(ordered))
    p1, p2 = "/" + "/".join(ordered), "/" + "/".join(shuffled)
    assert zoo.fs.info(p1)["intent"] == zoo.fs.info(p2)["intent"]
    assert listing_signature(zoo.fs, p1) == listing_signature(zoo.fs, p2)


# 2. redundant components (already in the closure) change nothing
@on_each_backend
@given(attrs=attr_sets, data=st.data())
def test_redundancy_is_harmless(backend, attrs, data):
    zoo = ZOOS[backend]
    closure = zoo.index.closure(attrs)
    p = "/" + "/".join(sorted(attrs))
    extra = data.draw(st.sampled_from(sorted(closure)))
    p_redundant = f"{p}/{extra}"
    assert zoo.fs.info(p)["intent"] == zoo.fs.info(p_redundant)["intent"]
    assert listing_signature(zoo.fs, p) == listing_signature(zoo.fs, p_redundant)


# 6. naming determinism + round-trip: every name ls shows resolves via cat
@on_each_backend
@settings(deadline=None)
@given(attrs=attr_sets, use_all=st.booleans())
def test_every_shown_name_cats_back_to_its_bytes(backend, attrs, use_all):
    zoo = ZOOS[backend]
    path = "/" + "/".join(sorted(attrs)) + ("/.all" if use_all else "")
    first = zoo.fs.ls(path, detail=True)
    assert first == zoo.fs.ls(path, detail=True)  # deterministic
    for entry in first:
        if entry["type"] != "file":
            continue
        data = zoo.fs.cat_file(entry["name"])
        assert hashlib.sha256(data).hexdigest() == entry["swarm_ref"]


# 9. coverage: everything in the extent is a file here or inside a listed child
@on_each_backend
@given(attrs=attr_sets)
def test_listing_covers_the_extent(backend, attrs):
    zoo = ZOOS[backend]
    intent = zoo.index.closure(attrs)
    path = "/" + "/".join(sorted(attrs))
    entries = zoo.fs.ls(path, detail=True)
    dirs = {
        e["name"].rsplit("/", 1)[-1]
        for e in entries
        if e["type"] == "directory"
    } - {".all", ".swarm", ".unfiled"}
    file_refs = {e["swarm_ref"] for e in entries if e["type"] == "file"}
    for obj in zoo.index.extent(intent):
        assert obj.ref in file_refs or (obj.intent & dirs), (
            f"{obj.label} is in extent({sorted(intent)}) but neither listed "
            f"nor covered by a shown child"
        )


# 8. reserved-namespace hygiene
@on_each_backend
def test_dot_attributes_rejected_on_write(backend):
    from conftest import make_index

    idx = make_index(backend)
    with pytest.raises(ValueError):
        idx.add_attribute(".hidden")
    with pytest.raises(ValueError):
        idx.add_attribute("a/b")
    idx.add_attribute("ok")
    with pytest.raises(ValueError):
        idx.add_attribute("child", parents=[".swarm"])


@on_each_backend
@given(attrs=attr_sets)
def test_reserved_names_never_appear_as_attributes(backend, attrs):
    path = "/" + "/".join(sorted(attrs))
    for entry in ZOOS[backend].fs.ls(path, detail=True):
        base = entry["name"].rsplit("/", 1)[-1]
        if entry["type"] == "directory":
            assert base == ".all" or not base.startswith(".")


@on_each_backend
def test_dotted_path_components_are_enoent(backend):
    with pytest.raises(FileNotFoundError):
        ZOOS[backend].fs.ls("/.nope")
    with pytest.raises(FileNotFoundError):
        ZOOS[backend].fs.info("/pet/.hidden")
