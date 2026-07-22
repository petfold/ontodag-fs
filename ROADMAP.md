# ROADMAP.md — ontodag-fs

## Step 0 — swarmfs FUSE mount (lives in the swarmfs repo, NOT here)

The "simple Swarm FUSE interface" is not new code: it is fsspec's generic FUSE
wrapper over the existing swarmfs backend. Deliverables **in swarmfs**:

- Verify `fsspec.fuse.run(SwarmFileSystem(...), "bzz-root-or-ref/", mountpoint)`
  works read-only against (a) the Memory/mock backend, (b) a Bee gateway.
  Fix any AbstractFileSystem conformance gaps it exposes (fsspec's FUSE wrapper
  is a good conformance test: it exercises ls/info/cat/open strictly).
- Add a `swarmfs mount <ref-or-bzz-url> <mountpoint>` console entry point
  (thin wrapper around fsspec.fuse.run) + README section "Mounting Swarm as a
  filesystem", with the fusepy/libfuse install caveat and a note that this is
  read-only for immutable references.
- Optional extra: `pytest -m fuse` integration test, skipped when libfuse is
  absent.

This both delivers the standalone Swarm-FUSE feature and de-risks the exact
mounting path ontodag-fs will reuse.

## v0 — read-only ontology view (ontodag-fs, days not weeks)

- `OntoDAGFileSystem(AbstractFileSystem)`: `ls`, `info`, `exists`, `cat_file`,
  `open(rb)`, `isdir/isfile`, `checksum` per SPEC §3, with the hybrid listing
  policy, `.all/`, `/.swarm/` read-through, naming/collision policy, and the
  per-concept lazy cache (SPEC §4).
- Dependency-injected OntoDAG handle + swarmfs instance; full test suite runs
  against in-memory backends, no Bee node, no FUSE.
- Invariant tests 1, 2, 6, 8 from SPEC §6 (the read-side ones).
- Manual milestone: mount Peter's actual ontology, browse it, judge whether
  the projection *feels* right. This validates everything downstream.
  **Executed 2026-07-22** end-to-end against the real local Bee node: the
  store.od categories merged into a fresh `swarm:ontodag-fs-demo` store,
  five real objects filed (bytes via /bytes, DAG committed via
  recordstore), browsed cold-start via `python -m ontodag_fs` (thin
  milestone CLI, ls/tree/cat/info/mount) and via an actual FUSE mount.
  Finding to judge: single-object tails yield dead-end directories — see
  DESIGN_DECISIONS "Acknowledged and deferred". Peter's own judgment of
  the feel is still the open item.

## v0.1 — filing

- `pipe_file` / `put_file` (store + assert, dedup-by-content), `rm`
  (retraction, `/.unfiled/`), `mv`, in-mount `cp` per SPEC §3.
- Classify-by-reference primitive (from `/.swarm/<ref>`).
- Postage-stamp error surfacing (PermissionError with actionable message).
- Invariant tests 3, 4, 5, 7.

## v1 — workflow layer

- CLI: `odag-fs file <ref|path> <concept-path>`, `odag-fs import
  <tree> --provenance TAG` (SPEC §5), `odag-fs mount`.
- `/.unfiled/` management; label rename.
- xattr exposure of intents (if fsspec's FUSE path allows; else document as
  needing the dedicated FUSE layer).

## Storage tiers and overlay (work in dependency repos; see DESIGN_DECISIONS #14–16)

Sequenced by need, not version-pinned. None of it changes ontodag-fs's
surface — it all arrives through the injected ConceptIndex / bytestore.

- **swarmfs**: public raw-reference read API (`read_reference`/
  `reference_size`) replacing ontodag-fs's use of the private
  `_read_reference`; then a disk bytestore (content-addressed directory
  keyed by BMT references, computed offline) behind the same interface.
- **recordstore**: local-directory backend with the same record format as
  the Swarm backend.
- **ontodag**: layered DAG — shared base hydrated from Swarm (read-only)
  + private overlay on disk; all writes routed to the overlay; base
  refresh = re-hydrate + re-merge. Whiteouts (retracting base facts)
  deferred.
- **workflow (v1+ here)**: `odag-fs publish` — promote overlay
  assertions to the shared base, uploading referenced local bytes to Swarm
  *first* (DESIGN_DECISIONS #16: nothing shared may dangle).

## Later, only if earned by usage

- `mkdir`/`rmdir` as concept creation/removal with deliberate intent semantics.
- Dedicated fusepy layer (better caching, non-blocking ops) under the unchanged
  fsspec backend.
- Query API beyond path syntax (OR/NOT outside paths).
- Automatic intent extraction hooks (transducer analog; mdl-fca integration).
- Feeds/mutable roots; ACT-protected objects.
