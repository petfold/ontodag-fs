"""What ontodag-fs relies on upstream, asserted so that a change announces itself.

Written 2026-08-03, after ontodag 0.10.0/0.10.1 shipped a new canonical-name
grammar (registry 3.0: reduced rationals of the SI anchor instead of integers in
base units) and this repo went on resolving typed-value paths to nodes that no
longer existed. Nothing failed loudly. `pip` installed the new ontodag happily,
because the floor was `>=0.4.0` with no ceiling, and ontodag-fs's own CI never
runs when ontodag changes — so both repos stayed green for two days while the
adapter was broken.

The lesson is ontodag's own, from its 0.10.1 post-mortem: a change to the
canonical-name grammar is a cross-cutting change, and the fan-out needs to be
written down somewhere that fails. That post-mortem listed the consumers *inside*
ontodag. This file is the same list drawn across the repo boundary.

Three kinds of dependency, each with its own failure mode:

  * **Compatibility signals** ontodag publishes on purpose — `REGISTRY_VERSION`
    and `CONTRACT_VERSION`. A bump means "assumptions may have moved"; pinning
    them here turns a silent behaviour change into one failing test that says
    where to look.
  * **The canonical-name grammar itself**, which is what actually broke. Asserted
    directly, because a registry *minor* bump is compatible and a major one may
    not be, and either way the names are the thing paths are made of.
  * **Private upstream API** (`_parse_parametric`, ontodag's CLI helpers,
    swarmfs's raw-reference reads). No version bound protects these: they carry
    no compatibility promise at all. These tests only catch *removal* — a rename
    that keeps the behaviour will still pass, and a silent change of behaviour
    will still slip. The real fix is public seams upstream, tracked as
    ontodag issue #13 and ROADMAP § "Storage tiers".
"""

from __future__ import annotations

import pytest
from ontodag.dag import OntoDAG

# What this repo was built and tested against. Update deliberately, with the
# canonical-name tests re-checked — not to make a red suite green.
REGISTRY_MAJOR = "4"
CONTRACT_VERSION = "0.1"


class TestCompatibilitySignals:
    def test_registry_major_is_the_one_we_built_against(self):
        """The unit registry carries its own MAJOR.MINOR compatibility contract.
        A major bump is ontodag saying canonical spellings may have changed —
        which is exactly what broke this adapter at registry 3.0."""
        from ontodag.dimensions import REGISTRY_VERSION

        major = REGISTRY_VERSION.split(".")[0]
        assert major == REGISTRY_MAJOR, (
            f"ontodag's unit registry is {REGISTRY_VERSION}, this repo was built "
            f"against {REGISTRY_MAJOR}.x. Canonical value names may have changed: "
            f"re-check tests/test_dimensions.py, the examples in SPEC.md §1 and "
            f"docs/USER_GUIDE.md, then move REGISTRY_MAJOR here."
        )

    def test_contract_version_is_the_one_we_built_against(self):
        import ontodag

        assert ontodag.CONTRACT_VERSION == CONTRACT_VERSION, (
            f"ontodag's contract is {ontodag.CONTRACT_VERSION}, this repo was "
            f"built against {CONTRACT_VERSION}. Read ontodag's docs/CONTRACT.md "
            f"for what changed in G1–G6 before moving this."
        )


class TestCapabilitiesTheFloorGuarantees:
    """Behaviour the declared dependency promises, asserted unconditionally.

    The distinction from `tests/test_file_store.py` matters, and it was found by
    rehearsing the release gate rather than reasoning about it. That file
    *feature-detects* metadata persistence and skips without it, which is right
    for someone running an out-of-contract ontodag — but it also meant a
    candidate that had *regressed* the feature sailed through the gate on skips:
    269 passed, 7 skipped, green. A skip is not a pass.

    So: anything the floor in pyproject.toml guarantees is asserted here without
    a feature check. If the installed ontodag cannot do it, that is either a
    regression upstream or an install that violates the pin, and both should be
    loud.
    """

    def test_the_native_store_persists_node_metadata(self):
        """ontodag >= 0.11.0. Objects are marked by `metadata["object"]` and
        carry their filename in `metadata["label"]`, so without this a
        file-backed store presents as an empty filesystem — no files, and no
        concept directories either, since empty extents suppress those too."""
        import os
        import tempfile

        from ontodag.dag import Item
        from ontodag.__main__ import _load_native, _save_native

        dag = OntoDAG()
        dag.put(Item("ref", metadata={"object": True, "label": "x.txt"}), [])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "probe.od")
            _save_native(dag, path)
            back = _load_native(path)
        assert back.nodes["ref"].metadata.get("label") == "x.txt", (
            "the installed ontodag's native .od store does not persist node "
            "metadata. ontodag-fs keeps object marks and display labels there, "
            "so a file-backed store would present as empty. This is guaranteed "
            "by the >=0.11.0 floor in pyproject.toml: either the installed "
            "ontodag is older than the pin allows, or upstream has regressed."
        )

    def test_the_empty_query_is_the_universe(self):
        """ontodag >= 0.10.1. `OntoDAGIndex._extent_nodes` uses `get([])` for the
        top concept, which is what keeps it correct on a partially resident DAG
        (tests/test_residency.py)."""
        dag = OntoDAG()
        dag.put("a", [])
        dag.put("b", ["a"])
        assert {n.name for n in dag.get([])} >= {"a", "b"}, (
            "dag.get([]) no longer returns everything; ontodag-fs resolves the "
            "top concept's extent with it."
        )


class TestTheCanonicalNameGrammar:
    """The specific thing that broke, asserted directly.

    Paths are made of these names, so a change here changes what every typed
    path resolves to. Registry versions are the announcement; this is the fact.
    """

    @pytest.fixture()
    def dag(self):
        dag = OntoDAG()
        for name, parents in (("dimension", []),
                              ("linear-dimension", ["dimension"]),
                              ("calendar-dimension", ["dimension"]),
                              ("weight", ["linear-dimension"]),
                              ("time", ["calendar-dimension"])):
            dag.put(name, parents)
        return dag

    @pytest.mark.parametrize("asserted,canonical", [
        ("weight(3kg)", "weight(3kg)"),
        ("weight(3000g)", "weight(3kg)"),
        # the rational that forced percent-encoding of path components
        ("weight(4.5kg)", "weight(9/2kg)"),
        # exact below the old base unit: a boundary error before registry 3.0
        ("weight(0.0005g)", "weight(1/2000000kg)"),
        ("weight(..5000g)", "weight(..5kg)"),
        # calendar reduced precision denotes the whole period
        ("time(2026-08)",
         "time(2026-08-01T00:00:00Z..2026-08-31T23:59:59Z)"),
    ])
    def test_canonical_form_is_what_paths_were_built_for(
            self, dag, asserted, canonical):
        _head, _kind, got = dag._parse_parametric(asserted)
        assert got == canonical, (
            f"ontodag now canonicalises {asserted!r} to {got!r}, not "
            f"{canonical!r}. Typed-value paths resolve through these names, so "
            f"listings, SPEC.md §1 and the docs examples all need re-checking."
        )

    def test_a_malformed_value_still_raises_rather_than_resolving(self, dag):
        """The read surface maps this to ENOENT; if it ever stops raising, a
        misspelled value would silently become a valid empty directory."""
        with pytest.raises(ValueError):
            dag._parse_parametric("weight(3zz)")


class TestPrivateUpstreamSurface:
    """Symbols with no compatibility promise, listed with why we need them.

    Catches removal, not renaming-with-equivalent-behaviour. Each entry should
    shrink as public seams appear upstream.
    """

    def test_dimension_parsing_hook_exists(self):
        """OntoDAGIndex resolves typed path components through this. It degrades
        to treating every name as opaque if absent — so without this test the
        loss would show up as 'typed directories mysteriously vanished'."""
        assert hasattr(OntoDAG(), "_parse_parametric"), (
            "ontodag.dag.OntoDAG._parse_parametric is gone. ontodag-fs "
            "resolves typed-value path components with it (ontodag_index.py); "
            "find the public equivalent and switch to it."
        )

    def test_cli_store_helpers_exist(self):
        """`odag-fs` opens the same stores as `odag` by reusing its resolution:
        accepted milestone tooling until a public seam exists (ontodag #13)."""
        import ontodag.__main__ as odag_cli

        for name in ("_make_backend", "_read_config", "_resolve_store"):
            assert hasattr(odag_cli, name), (
                f"ontodag.__main__.{name} is gone; ontodag_fs/__main__.py "
                f"builds its filesystem with it. See ontodag issue #13 for the "
                f"public seam this is waiting on."
            )

    def test_swarmfs_raw_reference_reads_exist(self):
        """Object bytes are addressed by reference, not by manifest path, and
        swarmfs exposes that only internally today (ROADMAP § Storage tiers)."""
        from swarmfs import SwarmFileSystem

        for name in ("_read_reference", "_get_reader"):
            assert hasattr(SwarmFileSystem, name), (
                f"swarmfs.SwarmFileSystem.{name} is gone; ontodag-fs reads "
                f"object bytes by raw reference with it (fs.py). ROADMAP asks "
                f"swarmfs for a public `read_reference`/`reference_size`."
            )

    def test_the_reader_can_report_a_size(self):
        from swarmfs.join import VerifyingReader

        assert hasattr(VerifyingReader, "bytes_size"), (
            "swarmfs's reader lost bytes_size; ontodag-fs needs it to fill in "
            "st_size without fetching the whole object (fs.py::_swarm_size)."
        )
