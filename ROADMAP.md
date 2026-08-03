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

## Upstream: ontodag dimension lattices (design agreed 2026-07-30)

ontodag has **parametric items** — `weight(..5000000mg)`,
`time(2026-06-01T00:00:00Z..2026-08-31T23:59:59Z)`, `geo(u2e)` — ordered by
computed containment of denoted value sets (`ontodag/docs/DIMENSIONS.md`;
shipped in ontodag 0.4.0, 2026-07-30). **Implemented here 2026-07-31**, in
`OntoDAGIndex` alone (`closure`/`add_object` — the fs layer needed zero
changes, since closure-success already means directory-exists everywhere):
virtual directories, sugar-on-lookup, canonical listings, guard mapping —
`tests/test_dimensions.py`. OntoDAG-backed index only; `InMemoryIndex` has
no DAG to declare dimensions in. The path semantics as implemented:

- **Parametric path components are single attribute constraints**, so hard
  rule 3 (no query operators in paths) is *not* violated: `/photo/time(a..b)/`
  is one category whose extension is computed, and concatenation stays AND.
  (Interactive shells need quoting for parentheses; annoyance, not blocker.)
- **The canonical grammar is NOT POSIX-legal — corrected 2026-08-03.** This
  section originally claimed it was ("only the exact components `.` and `..`
  are special to the kernel"), which held for registry 2.x, where canonical
  values were integers in base units. ontodag registry 3.0 made them *reduced
  rationals of the SI anchor*, so `weight(4.5kg)` stores as `weight(9/2kg)` —
  and `/` is the one character a path component can never carry. The symptom
  was a listing that lied: `ls` emitted `weight(9/2kg)` as a directory entry
  and the same filesystem's `isdir` denied it. Fixed by percent-encoding path
  components (`names.py`, SPEC § 2 Naming); the hazard is now covered by a
  name-consumer corpus (`tests/test_names.py`), the sibling of the one ontodag
  built after its own 0.10.1 post-mortem. Lesson recorded there: a change to
  the canonical-name grammar is a cross-cutting change, and this repo is one
  of the consumers.
- **Virtual directories.** A parametric component need not exist as a node —
  resolution parses it and evaluates the *virtual query term* (ontodag
  DIMENSIONS.md §8). `info()` on a syntactically valid term whose head is a
  declared dimension succeeds; the namespace is infinite but computed on
  demand, which is exactly hard rule 5 (lazy materialization). Malformed
  parameter or undeclared head → FileNotFoundError on read, EINVAL-mapped
  OSError on write. (Sub-base precision was in that list until registry 3.0
  made canonical values exact rationals; `weight(0.0005g)` is now an ordinary
  value, not a boundary error.)
- **Listings show present values only.** `ls /weight/` is the dimension's
  anchor star (its used values) — never an enumeration of the value space;
  `ls` under a virtual interval dir shows present matching values plus
  objects. Sort dimension listings by value (registry order), not
  lexicographically.
- **Sugar on lookup, readable on display** (the second half adopted
  2026-08-03). Accept `weight(3000g)` in a path and resolve to the canonical
  `weight(3kg)` (like case-insensitive lookup). readdir shows the name as
  `ontodag.surface.render` spells it — `time(2026-08)`, not
  `time(2026-08-01T00:00:00Z..2026-08-31T23:59:59Z)` — percent-encoded after
  rendering, where the result still needs it. Note hard rule 1 is untouched: it
  governs *object* labels; attribute names are identities, and canonical
  strings remain the stored names and the only thing intents ever contain.

  What made this a five-line change rather than a naming project: render only
  ever picks a spelling the dimensions grammar already accepts ("policy picks,
  vocabulary defines"), so a rendered name resolves through the existing sugar
  path with no elaboration step on this side, and `elaborate` is never called
  here. It also mostly retires the `%2F` escape as a side effect —
  `weight(9/2kg)` renders to `weight(4500g)` — leaving encoding as the backstop
  for values no unit makes whole (`length(10/33m)`). Per ontodag's
  SURFACE_LAYER.md §7 there is an honest switch: `render_names=`,
  `$ONTODAG_SURFACE`, `odag-fs --raw`.
- **Filing hits ontodag's new boundary checks**: filing under provably
  disjoint same-dimension components (`/weight(..2000g)/weight(3000g..)/`)
  raises ontodag's disjoint-parents guard → EINVAL; as a read query the same
  path is legal and provably empty. Same-dimension components pre-intersect
  exactly, so the order-insensitivity invariant extends unchanged.
- **Regions and generated sets need zero fs work**: `/photo/balaton-region/`
  and `/offers/saturdays/` are ordinary nodes over generated children
  (DIMENSIONS.md §9) and already browse today.
