"""Property-based read-side invariants 1, 2, 6, 8 from SPEC §6."""

from __future__ import annotations

import hashlib

import pytest
from hypothesis import given, settings, strategies as st

from ontodag_fs.memory import InMemoryIndex

from conftest import ATTRIBUTES, build_zoo

# read-only tests: one shared instance is safe and fast
ZOO = build_zoo()

attr_sets = st.sets(st.sampled_from(sorted(ATTRIBUTES)), min_size=1, max_size=4)


def listing_signature(fs, path):
    """(basename, type, swarm_ref) triples — path-prefix-independent."""
    return {
        (e["name"].rsplit("/", 1)[-1], e["type"], e.get("swarm_ref"))
        for e in fs.ls(path, detail=True)
    }


# 1. resolve(p) == resolve(shuffle(p))
@given(attrs=attr_sets, data=st.data())
def test_order_insensitivity(attrs, data):
    ordered = sorted(attrs)
    shuffled = data.draw(st.permutations(ordered))
    p1, p2 = "/" + "/".join(ordered), "/" + "/".join(shuffled)
    assert ZOO.fs.info(p1)["intent"] == ZOO.fs.info(p2)["intent"]
    assert listing_signature(ZOO.fs, p1) == listing_signature(ZOO.fs, p2)


# 2. redundant components (already in the closure) change nothing
@given(attrs=attr_sets, data=st.data())
def test_redundancy_is_harmless(attrs, data):
    closure = ZOO.index.closure(attrs)
    p = "/" + "/".join(sorted(attrs))
    extra = data.draw(st.sampled_from(sorted(closure)))
    p_redundant = f"{p}/{extra}"
    assert ZOO.fs.info(p)["intent"] == ZOO.fs.info(p_redundant)["intent"]
    assert listing_signature(ZOO.fs, p) == listing_signature(ZOO.fs, p_redundant)


# 6. naming determinism + round-trip: every name ls shows resolves via cat
@settings(deadline=None)
@given(attrs=attr_sets, use_all=st.booleans())
def test_every_shown_name_cats_back_to_its_bytes(attrs, use_all):
    path = "/" + "/".join(sorted(attrs)) + ("/.all" if use_all else "")
    first = ZOO.fs.ls(path, detail=True)
    assert first == ZOO.fs.ls(path, detail=True)  # deterministic
    for entry in first:
        if entry["type"] != "file":
            continue
        data = ZOO.fs.cat_file(entry["name"])
        assert hashlib.sha256(data).hexdigest() == entry["swarm_ref"]


# 8. reserved-namespace hygiene
def test_dot_attributes_rejected_on_write():
    idx = InMemoryIndex()
    with pytest.raises(ValueError):
        idx.add_attribute(".hidden")
    with pytest.raises(ValueError):
        idx.add_attribute("a/b")
    idx.add_attribute("ok")
    with pytest.raises(ValueError):
        idx.add_attribute("child", parents=[".swarm"])


@given(attrs=attr_sets)
def test_reserved_names_never_appear_as_attributes(attrs):
    path = "/" + "/".join(sorted(attrs))
    for entry in ZOO.fs.ls(path, detail=True):
        base = entry["name"].rsplit("/", 1)[-1]
        if entry["type"] == "directory":
            assert base == ".all" or not base.startswith(".")


def test_dotted_path_components_are_enoent():
    with pytest.raises(FileNotFoundError):
        ZOO.fs.ls("/.nope")
    with pytest.raises(FileNotFoundError):
        ZOO.fs.info("/pet/.hidden")
