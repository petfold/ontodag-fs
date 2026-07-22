"""Hybrid listing policy, naming/collision policy, reachability (SPEC §2)."""

from __future__ import annotations


def basenames(fs, path, type=None):
    entries = fs.ls(path, detail=True)
    return {
        e["name"].rsplit("/", 1)[-1]
        for e in entries
        if type is None or e["type"] == type
    }


def test_root_shows_immediate_subconcepts_and_reserved_dirs(zoo):
    # mammal/pet/bird etc. are strictly below animal, so only the immediate
    # lattice children appear at the top — plus the reserved namespaces.
    assert basenames(zoo.fs, "/", "directory") == {
        "animal", "document", ".all", ".swarm", ".unfiled",
    }
    assert basenames(zoo.fs, "/", "file") == set()


def test_children_are_immediate_subconcepts_only(zoo):
    assert basenames(zoo.fs, "/animal", "directory") == {
        "mammal", "pet", "bird", ".all",
    }


def test_equal_extent_sibling_attributes_are_both_shown(zoo):
    # Under /pet, the bird and canary refinements have the same extent
    # (tweety) — same sub-concept, two facet names; both are listed.
    dirs = basenames(zoo.fs, "/pet", "directory")
    assert {"bird", "canary"} <= dirs


def test_plain_ls_shows_only_object_concept_members(zoo):
    # rex is maximally described at {dog,...}, so it appears in plain ls
    # exactly there, not at broader concepts.
    assert basenames(zoo.fs, "/pet/mammal/dog", "file") == {"rex.jpg", "notes.txt"}
    assert basenames(zoo.fs, "/animal", "file") == set()
    assert basenames(zoo.fs, "/wolf", "file") == {"pack.txt"}


def test_all_flattens_the_full_extent(zoo):
    h1, h2 = zoo.refs["dognotes"][:8], zoo.refs["catnotes"][:8]
    assert basenames(zoo.fs, "/pet/.all") == {
        "rex.jpg", "whiskers.jpg", "tweety.png",
        f"notes~{h1}.txt", f"notes~{h2}.txt",
    }
    # everything filed is one .all away from the root; unfiled is excluded
    assert len(zoo.fs.ls("/.all")) == len(zoo.store) - 1


def test_label_collision_gets_shorthash_suffix_before_extension(zoo):
    names = basenames(zoo.fs, "/mammal/.all")
    assert f"notes~{zoo.refs['dognotes'][:8]}.txt" in names
    assert "notes.txt" not in names  # ambiguous plain name never shown


def test_unique_label_shown_plain_and_suffixed_form_also_resolves(zoo):
    # unique within /dog, so shown plain — but the suffixed form must
    # resolve too (SPEC §2 naming)
    assert zoo.fs.cat_file("/dog/notes.txt") == b"dog notes"
    suffixed = f"/dog/notes~{zoo.refs['dognotes'][:8]}.txt"
    assert zoo.fs.cat_file(suffixed) == b"dog notes"


def test_reachability_is_universal_listing_is_scoped(zoo):
    # rex.jpg is not listed at /animal, but the path still resolves
    assert "rex.jpg" not in basenames(zoo.fs, "/animal")
    assert zoo.fs.exists("/animal/rex.jpg")
    assert zoo.fs.cat_file("/animal/rex.jpg") == b"rex the dog"


def test_ls_of_a_file_returns_its_entry(zoo):
    entries = zoo.fs.ls("/wolf/pack.txt", detail=True)
    assert len(entries) == 1
    assert entries[0]["type"] == "file"
    assert entries[0]["swarm_ref"] == zoo.refs["pack"]


def test_unknown_attribute_is_enoent(zoo):
    import pytest

    with pytest.raises(FileNotFoundError):
        zoo.fs.ls("/pet/unicorn")


def test_coverage_rule_rescues_single_object_tails(zoo_tail):
    """The v0-milestone dead end (decision #18): rex, the only pet, is a
    dog — /animal/pet must list him, not just .all/."""
    fs = zoo_tail.fs
    assert basenames(fs, "/animal/pet", "file") == {"rex.txt"}
    # the identical-extent child stays hidden; the object is the entry
    assert basenames(fs, "/animal/pet", "directory") == {".all"}
    assert fs.cat_file("/animal/pet/rex.txt") == b"rex"
    # still listed at his object concept, and reachable by the typed path
    assert basenames(fs, "/dog", "file") == {"rex.txt"}
    assert fs.cat_file("/animal/pet/dog/rex.txt") == b"rex"


def test_display_position_reflows_as_population_grows(zoo_tail):
    """Accepted trade-off of #18: filing a second pet makes dog/ refine, so
    rex moves from /animal/pet into /animal/pet/dog — still reachable."""
    from conftest import seed

    fs, index = zoo_tail.fs, zoo_tail.index
    index.add_attribute("cat", ["animal", "pet"])
    index.add_object(seed(zoo_tail.store, b"tom"), "tom.txt", {"cat"})
    assert basenames(fs, "/animal/pet", "directory") == {"dog", "cat", ".all"}
    assert basenames(fs, "/animal/pet", "file") == set()
    assert fs.cat_file("/animal/pet/dog/rex.txt") == b"rex"
    assert fs.cat_file("/animal/pet/rex.txt") == b"rex"  # reachability holds


def test_find_terminates_and_sees_every_object(zoo):
    found = zoo.fs.find("/")
    refs = {e["swarm_ref"] for e in zoo.fs.ls("/.all", detail=True)}
    assert refs == {zoo.refs[k] for k in zoo.refs if k != "orphan"}
    assert any(name.endswith("rex.jpg") for name in found)
