"""v0 is read-only: every write method refuses with a reasoned message."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "call",
    [
        lambda fs: fs.mkdir("/pet/hamster"),
        lambda fs: fs.makedirs("/pet/hamster"),
        lambda fs: fs.rmdir("/pet"),
        lambda fs: fs.pipe_file("/pet/x.txt", b"data"),
        lambda fs: fs.put_file("/tmp/x", "/pet/x.txt"),
        lambda fs: fs.rm("/dog/rex.jpg"),
        lambda fs: fs.rm_file("/dog/rex.jpg"),
        lambda fs: fs.mv("/dog/rex.jpg", "/cat/rex.jpg"),
        lambda fs: fs.cp_file("/dog/rex.jpg", "/cat/rex.jpg"),
        lambda fs: fs.touch("/pet/empty"),
        lambda fs: fs.open("/pet/x.txt", "wb"),
    ],
)
def test_write_methods_raise_notimplemented(zoo, call):
    with pytest.raises(NotImplementedError):
        call(zoo.fs)


def test_no_uploads_ever_happen_in_v0(zoo):
    # read everything reachable, then confirm zero bytes were posted
    zoo.fs.find("/")
    for entry in zoo.fs.ls("/.all", detail=True):
        zoo.fs.cat_file(entry["name"])
    assert zoo.client.uploads == []


def test_cache_invalidation_on_index_mutation(zoo):
    from conftest import seed

    before = zoo.fs.ls("/wolf")
    ref = seed(zoo.store, b"lone wolf")
    zoo.index.add_object(ref, "lone.txt", {"wolf"})
    after = zoo.fs.ls("/wolf")
    assert "/wolf/lone.txt" in after
    assert "/wolf/lone.txt" not in before
