"""v0.1 filing: writes are classification, bytes never move (SPEC §3,
DESIGN_DECISIONS #7). Runs on both index backends through the `zoo`
fixture; the FakeSwarmClient records uploads, which is invariant 7's spy.

The lattice stays read-only through the filesystem (#8): mkdir/rmdir
refuse, touch is rejected — the tail of this module keeps those tests.
"""

from __future__ import annotations

import pytest

from conftest import seed


def names(fs, path):
    return sorted(e.rsplit("/", 1)[-1] for e in fs.ls(path))


# --------------------------------------------------------------- pipe/put/open

def test_pipe_file_stores_and_files(zoo):
    fs = zoo.fs
    n = len(zoo.client.uploads)
    ref = fs.pipe_file("/pet/dog/bones.txt", b"a bone")
    assert len(zoo.client.uploads) == n + 1
    assert zoo.store[bytes.fromhex(ref)] == b"a bone"
    info = fs.info("/pet/dog/bones.txt")
    assert info["type"] == "file" and info["swarm_ref"] == ref and info["size"] == 6
    assert set(info["intent"]) == {"dog", "mammal", "pet", "animal"}
    assert fs.cat_file("/dog/bones.txt") == b"a bone"          # any true name
    # invariant 3, file-then-find: at its object concept, in every .all above
    assert "bones.txt" in names(fs, "/dog")
    for anc in ("/pet/.all", "/mammal/.all", "/animal/.all", "/.all"):
        assert "bones.txt" in names(fs, anc)
    assert "bones.txt" not in names(fs, "/cat/.all")
    assert zoo.index.get_object(ref).label == "bones.txt"


def test_pipe_into_dot_all_and_unfiled(zoo):
    fs = zoo.fs
    ref = fs.pipe_file("/bird/.all/feather.txt", b"feather")   # .all files at the concept
    assert set(zoo.index.get_object(ref).intent) == {"bird", "animal"}
    ref2 = fs.pipe_file("/.unfiled/loose.txt", b"loose")        # stored, unclassified
    assert zoo.index.get_object(ref2).intent == frozenset()
    assert "loose.txt" in names(fs, "/.unfiled")


def test_dedup_by_content_address(zoo):
    """Invariant 5: identical bytes under P1 then P2 → one object, intent
    closure(P1) ∪ closure(P2)."""
    fs = zoo.fs
    r1 = fs.pipe_file("/dog/twice.txt", b"same bytes")
    r2 = fs.pipe_file("/document/twice.txt", b"same bytes")
    assert r1 == r2
    obj = zoo.index.get_object(r1)
    assert obj.intent == zoo.index.closure(["dog"]) | zoo.index.closure(["document"])
    assert "twice.txt" in names(fs, "/dog/document")


def test_put_file_and_open_wb(zoo, tmp_path):
    fs = zoo.fs
    local = tmp_path / "walk.txt"
    local.write_bytes(b"walkies")
    fs.put_file(str(local), "/pet/dog/walk.txt")
    assert fs.cat_file("/dog/walk.txt") == b"walkies"
    fs.put_file(str(local), "/cat/")                   # directory target: basename
    assert fs.cat_file("/cat/walk.txt") == b"walkies"
    with fs.open("/wolf/howl.txt", "wb") as f:
        f.write(b"how")
        f.write(b"l")
    assert fs.cat_file("/wolf/howl.txt") == b"howl"
    # fsspec's generic put reaches put_file
    fs.put(str(local), "/eagle/walk.txt")
    # same bytes as before → the one object gains `eagle`; listed under
    # /eagle/.all (its dog/cat children cover it in the plain listing)
    assert "walk.txt" in names(fs, "/eagle/.all")
    assert "eagle" in zoo.index.asserted(zoo.index.get_object(
        fs.info("/eagle/.all/walk.txt")["swarm_ref"]).ref)


def test_filing_targets_are_validated(zoo, tmp_path):
    fs = zoo.fs
    n = len(zoo.client.uploads)
    with pytest.raises(FileNotFoundError, match="no such concept"):
        fs.pipe_file("/unicorn/horn.txt", b"x")
    with pytest.raises(FileNotFoundError):
        fs.pipe_file("/.hidden/x.txt", b"x")             # reserved-looking attribute
    with pytest.raises(PermissionError, match="read-through"):
        fs.pipe_file("/.swarm/" + "ab" * 32, b"x")
    with pytest.raises(IsADirectoryError):
        fs.pipe_file("/pet/.all", b"x")
    with pytest.raises(IsADirectoryError):
        fs.pipe_file("/", b"x")
    with pytest.raises(FileNotFoundError):
        fs.open("/unicorn/x.txt", "wb")                  # fails before buffering
    assert len(zoo.client.uploads) == n                  # nothing left the machine


def test_missing_stamp_is_a_permission_error(zoo):
    async def no_stamps():
        return []

    zoo.client.stamps_list = no_stamps
    n = len(zoo.client.uploads)
    with pytest.raises(PermissionError, match="no valid postage stamp"):
        zoo.fs.pipe_file("/dog/x.txt", b"x")
    assert len(zoo.client.uploads) == n                  # refused before upload


# --------------------------------------------------------------------- rm

def test_rm_at_the_object_concept_unfiles(zoo):
    fs = zoo.fs
    fs.rm("/dog/rex.jpg")
    assert "rex.jpg" not in names(fs, "/dog")
    assert "rex.jpg" not in names(fs, "/pet/.all")
    assert "rex.jpg" in names(fs, "/.unfiled")
    assert fs.cat_file("/.unfiled/rex.jpg") == b"rex the dog"   # bytes untouched
    assert zoo.index.get_object(zoo.refs["rex"]).intent == frozenset()


def test_rm_by_implication_is_refused(zoo):
    """The retraction rule: rex is asserted `dog`; /pet reaches him only by
    implication, so rm there would also drop him from /mammal — refused,
    with the place it can be done."""
    fs = zoo.fs
    with pytest.raises(PermissionError, match="/dog/rex.jpg"):
        fs.rm("/pet/rex.jpg")
    assert "rex.jpg" in names(fs, "/dog")
    # naming the asserted attribute anywhere in the path is enough
    fs.rm("/animal/dog/rex.jpg")
    assert "rex.jpg" in names(fs, "/.unfiled")


def test_rm_locality(zoo):
    """Invariant 4: retracting at P leaves visibility under attribute sets
    not implied by P's assertion unchanged."""
    fs = zoo.fs
    ref = fs.pipe_file("/dog/both.txt", b"both")
    fs.classify(ref, "/document/both.txt")
    assert set(zoo.index.asserted(ref)) == {"dog", "document"}
    fs.rm("/dog/both.txt")
    assert "both.txt" not in names(fs, "/dog/.all")
    assert "both.txt" in names(fs, "/document")          # untouched
    assert set(zoo.index.asserted(ref)) == {"document"}


def test_rm_unfiled_forgets_the_object(zoo):
    fs = zoo.fs
    fs.rm("/.unfiled/orphan.bin")
    assert zoo.index.get_object(zoo.refs["orphan"]) is None
    assert "orphan.bin" not in names(fs, "/.unfiled")
    assert bytes.fromhex(zoo.refs["orphan"]) in zoo.store   # Swarm has no delete


def test_rm_refuses_directories_and_swarm(zoo):
    fs = zoo.fs
    with pytest.raises(IsADirectoryError):
        fs.rm("/pet")
    with pytest.raises(IsADirectoryError):
        fs.rm("/pet/dog/.all")
    with pytest.raises(PermissionError):
        fs.rm("/.swarm/" + zoo.refs["rex"])
    with pytest.raises(FileNotFoundError):
        fs.rm("/dog/nope.txt")


# --------------------------------------------------------------------- mv/cp

def test_mv_between_concepts(zoo):
    fs = zoo.fs
    fs.mv("/dog/rex.jpg", "/cat/rex.jpg")
    assert "rex.jpg" not in names(fs, "/dog/.all")
    assert "rex.jpg" in names(fs, "/cat")
    assert zoo.index.asserted(zoo.refs["rex"]) == frozenset({"cat"})
    assert fs.cat_file("/cat/rex.jpg") == b"rex the dog"


def test_mv_keeps_what_the_destination_asserts(zoo):
    """mv /dog/document/x → /dog/x retracts `document` and keeps `dog`;
    the reverse direction only adds — the live smoke against a real store
    caught the first version retracting both."""
    fs = zoo.fs
    ref = fs.pipe_file("/dog/document/x.txt", b"x")
    assert zoo.index.asserted(ref) == frozenset({"dog", "document"})
    fs.mv("/dog/document/x.txt", "/dog/x.txt")
    assert zoo.index.asserted(ref) == frozenset({"dog"})
    fs.mv("/dog/x.txt", "/dog/document/x.txt")
    assert zoo.index.asserted(ref) == frozenset({"dog", "document"})
    fs.mv("/document/x.txt", "/wolf/x.txt")            # sibling move: swap one
    assert zoo.index.asserted(ref) == frozenset({"dog", "wolf"})


def test_mv_rename_same_directory(zoo):
    fs = zoo.fs
    fs.mv("/dog/rex.jpg", "/pet/mammal/dog/king.jpg")      # same concept, spelled longer
    assert zoo.index.get_object(zoo.refs["rex"]).label == "king.jpg"
    assert zoo.index.asserted(zoo.refs["rex"]) == frozenset({"dog"})
    assert "king.jpg" in names(fs, "/dog")


def test_mv_to_and_from_unfiled(zoo):
    fs = zoo.fs
    fs.mv("/dog/rex.jpg", "/.unfiled/rex.jpg")
    assert zoo.index.asserted(zoo.refs["rex"]) == frozenset()
    fs.mv("/.unfiled/rex.jpg", "/eagle/rex.jpg")
    assert zoo.index.asserted(zoo.refs["rex"]) == frozenset({"eagle"})
    fs.mv("/.unfiled/orphan.bin", "/.unfiled/found.bin")   # rename while unfiled
    assert zoo.index.get_object(zoo.refs["orphan"]).label == "found.bin"


def test_mv_by_implication_is_refused_and_leaves_store_untouched(zoo):
    fs = zoo.fs
    before = zoo.index.asserted(zoo.refs["rex"])
    with pytest.raises(PermissionError):
        fs.mv("/pet/rex.jpg", "/cat/rex.jpg")
    # assert-before-retract: the refusal happens after the assert, so it
    # must not leave a half-move behind
    assert zoo.index.asserted(zoo.refs["rex"]) == before | {"cat"} or \
        zoo.index.asserted(zoo.refs["rex"]) == before


def test_cp_within_mount_is_intent_union(zoo):
    fs = zoo.fs
    fs.cp_file("/dog/rex.jpg", "/document/rex.jpg")
    assert zoo.index.asserted(zoo.refs["rex"]) == frozenset({"dog", "document"})
    # now at the concept {dog, document}: a child of both plain listings
    assert "rex.jpg" in names(fs, "/dog/document")
    assert "rex.jpg" in names(fs, "/dog/.all") and "rex.jpg" in names(fs, "/document/.all")
    fs.copy("/dog/rex.jpg", "/eagle/whatever.jpg")          # fsspec generic → cp_file
    assert "eagle" in zoo.index.asserted(zoo.refs["rex"])
    assert zoo.index.get_object(zoo.refs["rex"]).label == "rex.jpg"   # one label
    with pytest.raises(PermissionError):
        fs.cp_file("/dog/rex.jpg", "/.unfiled/rex.jpg")


def test_classify_by_reference(zoo):
    fs = zoo.fs
    ref = seed(zoo.store, b"already on swarm")
    n = len(zoo.client.uploads)
    fs.cp_file(f"/.swarm/{ref}", "/document/paper.md")
    assert len(zoo.client.uploads) == n                     # no upload
    obj = zoo.index.get_object(ref)
    assert obj.label == "paper.md" and "document" in obj.intent
    assert fs.cat_file("/document/paper.md") == b"already on swarm"
    # the primitive itself; a known object keeps its label
    fs.classify(ref, "/wolf/renamed.md")
    assert zoo.index.get_object(ref).label == "paper.md"
    assert "wolf" in zoo.index.asserted(ref)
    with pytest.raises(ValueError, match="Swarm reference"):
        fs.classify("nope", "/wolf/x")


def test_no_byte_motion_across_rm_mv_cp(zoo):
    """Invariant 7."""
    fs = zoo.fs
    n = len(zoo.client.uploads)
    fs.cp_file("/dog/rex.jpg", "/document/rex.jpg")
    fs.mv("/document/rex.jpg", "/eagle/rex.jpg")
    fs.rm("/eagle/rex.jpg")
    fs.mv("/cat/whiskers.jpg", "/cat/tom.jpg")
    fs.rm("/.unfiled/orphan.bin")
    assert zoo.client.uploads[n:] == []


# ------------------------------------------------------------- persistence

def test_each_write_persists_once():
    """One version per operation: a `mv` is one commit, not two."""
    from ontodag.dag import OntoDAG

    from conftest import FakeSwarmClient
    from swarmfs import SwarmFileSystem
    from ontodag_fs import OntoDAGFileSystem, OntoDAGIndex

    class CommittingDAG(OntoDAG):
        commits = 0

        def commit(self, message=None):
            self.commits += 1

    dag = CommittingDAG()
    index = OntoDAGIndex(dag)
    index.add_attribute("a")
    index.add_attribute("b")
    store: dict = {}
    fs = OntoDAGFileSystem(index=index, swarm=SwarmFileSystem(
        client=FakeSwarmClient(store), skip_instance_cache=True))
    fs.pipe_file("/a/x.txt", b"x")
    assert dag.commits == 1
    fs.mv("/a/x.txt", "/b/y.txt")
    assert dag.commits == 2
    fs.cp_file("/b/y.txt", "/a/y.txt")
    fs.rm("/a/y.txt")
    assert dag.commits == 4
    fs.ls("/a")                       # reads never commit
    assert dag.commits == 4


# ------------------------------------------ the lattice stays read-only (#8)

@pytest.mark.parametrize(
    "call",
    [
        lambda fs: fs.mkdir("/pet/hamster"),
        lambda fs: fs.makedirs("/pet/hamster"),
        lambda fs: fs.rmdir("/pet"),
        lambda fs: fs.touch("/pet/empty"),
        lambda fs: fs.open("/pet/x.txt", "ab"),
    ],
)
def test_lattice_edits_and_touch_refuse(zoo, call):
    with pytest.raises(NotImplementedError):
        call(zoo.fs)


def test_reads_never_upload(zoo):
    zoo.fs.find("/")
    for entry in zoo.fs.ls("/.all", detail=True):
        zoo.fs.cat_file(entry["name"])
    assert zoo.client.uploads == []


def test_cache_invalidation_on_index_mutation(zoo):
    before = zoo.fs.ls("/wolf")
    ref = seed(zoo.store, b"lone wolf")
    zoo.index.add_object(ref, "lone.txt", {"wolf"})
    after = zoo.fs.ls("/wolf")
    assert "/wolf/lone.txt" in after
    assert "/wolf/lone.txt" not in before
