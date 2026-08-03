"""Browsing a store held in ontodag's native `.od` text file.

The cheapest backend: no Bee node, no recordstore, just a text file. It was
also, until ontodag learned to persist node metadata, the one backend
ontodag-fs could not read. `.od` recorded names and edges only, so a DAG saved
and reloaded through it came back with every `metadata` empty — and objects are
marked by `metadata["object"]` with their filename in `metadata["label"]`
(#12). Every object therefore read back as a category, which emptied every
extent, which suppressed the concept directories too: `odag-fs -s store.od ls /`
printed `.all/` and nothing else against a store full of objects.

That was fixed upstream rather than worked around here. ontodag's native format
now carries metadata on `#:meta` comment lines, which keeps object marks *and*
labels — the reason to fix it there: a local fallback could have inferred
object-ness from the shape of a name, but nothing local could have recovered a
label, since this repo persists no state of its own (CLAUDE.md).

These tests skip on an ontodag that predates that fix, rather than asserting
the degraded behaviour: the degradation is not a contract worth pinning.
"""

from __future__ import annotations

import os
import tempfile

import pytest
from ontodag.dag import Item, OntoDAG
from swarmfs import SwarmFileSystem

from conftest import FakeSwarmClient, seed
from ontodag_fs import OntoDAGFileSystem, OntoDAGIndex


def _native_store_keeps_metadata() -> bool:
    """Does the installed ontodag persist node metadata in a `.od` file?"""
    try:
        from ontodag.__main__ import _load_native, _save_native
    except ImportError:                                   # pragma: no cover
        return False
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "probe.od")
        dag = OntoDAG()
        dag.put(Item("probe", metadata={"object": True, "label": "p.txt"}), [])
        _save_native(dag, path)
        return _load_native(path).nodes["probe"].metadata.get("label") == "p.txt"


pytestmark = pytest.mark.skipif(
    not _native_store_keeps_metadata(),
    reason="needs an ontodag whose native .od store persists node metadata "
           "(landed after 0.10.1; see ontodag CHANGELOG, 'The native .od "
           "store persists node metadata')",
)

LABELS = {"light": "light.txt", "heavy": "heavy.txt",
          "aug": "august.md", "sep": "september.md"}


@pytest.fixture()
def filed(tmp_path):
    """Objects and typed values, round-tripped through a real .od file."""
    from ontodag.__main__ import _load, _save

    dag = OntoDAG()
    for name, parents in (("parcel", []), ("doc", []), ("dimension", []),
                          ("linear-dimension", ["dimension"]),
                          ("calendar-dimension", ["dimension"]),
                          ("weight", ["linear-dimension"]),
                          ("time", ["calendar-dimension"])):
        dag.put(name, parents)

    store: dict[bytes, bytes] = {}
    refs = {}
    for key, (data, attrs) in {
        "light": (b"a light parcel", ["parcel", "weight(4.5kg)"]),
        "heavy": (b"a heavy parcel", ["parcel", "weight(9kg)"]),
        "aug": (b"an august note", ["doc", "time(2026-08)"]),
        # a second dated doc, so the time values refine and appear as
        # directories (a lone member cannot refine — SPEC §2)
        "sep": (b"a september note", ["doc", "time(2026-09)"]),
    }.items():
        ref = seed(store, data)
        refs[key] = ref
        dag.put(Item(ref, metadata={"object": True, "label": LABELS[key]}),
                attrs)
    loose = seed(store, b"unclassified")
    refs["loose"] = loose
    dag.put(Item(loose, metadata={"object": True, "label": "loose.txt"}), [])

    path = tmp_path / "store.od"
    _save(dag, str(path))
    fs = OntoDAGFileSystem(
        index=OntoDAGIndex(_load(str(path))),
        swarm=SwarmFileSystem(client=FakeSwarmClient(store),
                              skip_instance_cache=True),
    )
    return {"fs": fs, "refs": refs, "store": store, "path": path}


def _names(fs, path):
    return sorted(e.rsplit("/", 1)[-1] for e in fs.ls(path))


def test_files_are_listed_under_their_labels(filed):
    """The half a local fallback could never have delivered."""
    assert _names(filed["fs"], "/parcel/.all") == ["heavy.txt", "light.txt"]
    assert _names(filed["fs"], "/doc/.all") == ["august.md", "september.md"]


def test_bytes_are_readable_by_label(filed):
    fs = filed["fs"]
    assert fs.cat_file("/parcel/.all/light.txt") == b"a light parcel"
    assert fs.cat_file("/parcel/.all/light.txt", start=2, end=7) == b"light"
    assert fs.info("/parcel/.all/light.txt")["swarm_ref"] == filed["refs"]["light"]


def test_concepts_are_browsable(filed):
    """The symptom was total, not partial: empty extents made `children()`
    return nothing, so the categories vanished along with the files."""
    top = _names(filed["fs"], "/")
    assert {"parcel", "doc"} <= set(top)
    assert _names(filed["fs"], "/parcel") != [".all"]


def test_typed_values_work_over_a_file_store(filed):
    fs = filed["fs"]
    assert fs.isdir("/parcel/weight(..5kg)")
    assert _names(fs, "/parcel/weight(..5kg)/.all") == ["light.txt"]
    assert _names(fs, "/doc/time") == [".all", "time(2026-08)",
                                       "time(2026-09)"]        # rendered
    # the rational whose canonical name holds a '/', both spellings
    assert fs.isdir("/parcel/weight/weight(4500g)")
    assert fs.isdir("/parcel/weight/weight(9%2F2kg)")


def test_unfiled_survives_the_round_trip(filed):
    assert _names(filed["fs"], "/.unfiled") == ["loose.txt"]


def test_the_file_is_still_a_plain_text_store(filed):
    """Metadata rides on comment lines, so the store a human reads and diffs
    is unchanged in shape — worth pinning, since that is the whole reason the
    format could be extended without a version bump."""
    body = filed["path"].read_text(encoding="utf-8")
    assert body.startswith("# ontodag store v1")
    lines = body.splitlines()
    # one edge line per non-root node, plus a comment-borne annotation for each
    # object; ontodag's own tests cover byte-level canonicality
    assert any(ln.startswith("#:meta ") for ln in lines)
    assert sum(1 for ln in lines if not ln.startswith("#")) > 1
