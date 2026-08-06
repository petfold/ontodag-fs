# CLAUDE.md — ontodag-fs

## What this repo is

`ontodag-fs` is a **stateless fsspec adapter** that presents an OntoDAG concept
lattice as a browsable, mountable filesystem, with file bytes stored on Ethereum
Swarm via `swarmfs`.

One-line pitch: **Gifford's Semantic File System (SOSP '91) with an FCA concept
lattice instead of flat attributes, and content-addressed Swarm storage instead
of local disk.**

- **Paths are queries.** A path is an unordered *set* of attribute constraints.
  Resolution intersects attributes (FCA join), it does not walk labeled edges.
  `/pet/dog` and `/animal/mammal/dog` resolve to the same concept.
- **Directories are concepts.** Sub-directories of a concept are its
  sub-concepts (lattice children under the current query).
- **Files are classified objects.** An object = a Swarm reference (content
  address) + an intent (attribute set) + a display label. The same object
  legitimately appears under every concept whose extent contains it
  (hardlink semantics, never duplication).
- **Writes are classification.** Copying a file into `/a/b/` stores bytes via
  swarmfs and asserts intent ⊇ {a, b} in OntoDAG. Removing it from a concept
  dir retracts that classification only — never bytes (Swarm is immutable).

### Catching up with ontodag (2026-08-06, ontodag 0.16.0)

ontodag 0.16.0 brought a wave of editing/sharing/history features; the honest
adoption here is **one** of them, because this repo is a *browse* surface:
`--as-of ROOT` (a global flag, like `-s`/`--raw`) hydrates through ontodag's new
`Backend.load_at` instead of `load`, so `ls`/`tree`/`cat`/`info`/`mount` show the
store **as it was**. It fits with zero friction precisely because the view is
already read-only — a version *is* a root, so browsing the past only means
hydrating from a different one. Prefix resolution and the "this store keeps no
versions" error both come from upstream, so the message a user sees is the same
one `odag --as-of` gives.

Deliberately NOT adopted, and why: `move`/`remove --cone`/`undo`/`redo` all
*write* (this repo asserts classifications, never store surgery, and moving the
store's pointer from a mount would surprise every reader of it); `excerpt`/`diff`
are file-shaped tools for stores, not paths; `overlapping` has no obvious path
spelling — a candidate set is not a concept, so it would need a reserved
directory whose semantics nobody has designed (a `.maybe/` sibling of `.all/` is
the shape, if it is ever wanted). The floor moved to **>=0.16.0** for `load_at`
and the ceiling to **<0.17.0** (0.16.0's downstream gate passed).

## Architecture and division of labor

```
            FUSE mount (fsspec.fuse.run — deployment mode, not architecture)
                 │
        OntoDAGFileSystem (this repo: fsspec AbstractFileSystem, stateless glue)
           │                │
        OntoDAG           swarmfs
     (classifier/index)  (bytestore: fsspec backend for Swarm)
           │                │
       recordstore        Bee node / gateway
     (persistence of the DAG)
```

**This repo owns NO state.** Object→intent mappings live in OntoDAG; OntoDAG
persistence goes through recordstore; bytes go through swarmfs. If you find
yourself adding a database, cache file, or persisted mapping to this repo, stop
— that logic belongs in a dependency. In-memory caches are fine (see SPEC.md
§ Caching).

**This repo does NOT contain FUSE code.** It is a pure `AbstractFileSystem`
implementation. Mounting is done with fsspec's generic FUSE wrapper. A dedicated
fusepy layer is a possible *future* addition (see ROADMAP), only if fsspec's
wrapper proves inadequate in practice.

**This repo does NOT edit the DAG's structure.** v0/v1 are read-write for
*object filing* but read-only for the *lattice*. No `mkdir`-as-concept-creation
(see DESIGN_DECISIONS.md § Deferred). Concept creation goes through OntoDAG's
real API, outside this repo.

## Repos in the cluster (all under github.com/petfold)

| Repo | Role | This repo's relationship |
|---|---|---|
| `ontodag` | Concept DAG, FCA/MDL core | dependency — the index/classifier. Range is **>=0.16.0,<0.17.0** (floor: registry 3.0/4.0 canonical names — reduced rationals like `weight(9/2kg)` are why path components are percent-encoded — plus native-store metadata persistence; the floor moved to 0.16.0 on 2026-08-06 for `Backend.load_at`, which `--as-of` uses; ceiling: raised only after ontodag's downstream release gate runs this suite, see pyproject's comment — 0.16.0's gate passed). Its parametric dimensions surface here as virtual directories (shipped in ontodag-fs 0.1.0). See ROADMAP.md § "Upstream: ontodag dimension lattices" and DESIGN_DECISIONS.md #20. **A change to ontodag's canonical-name grammar is a change to this repo** — `tests/test_names.py` is the tripwire |
| `swarmfs` | fsspec backend for Swarm | dependency — the bytestore. Its authoritative API is the test-pinned [swarmfs REFERENCE.md](https://github.com/petfold/swarmfs/blob/main/docs/REFERENCE.md) (local: `../swarmfs/docs/REFERENCE.md`). The private-`_read_reference` gap was closed 2026-08-04: swarmfs 0.8.0 grew public `read_reference`/`reference_size` (documented in its reference), and this repo's floor moved to `swarmfs>=0.8.0` |
| `recordstore` | versioned key→record store over Swarm | indirect (via ontodag persistence; live tests use it directly). Authoritative API: the test-pinned [recordstore REFERENCE.md](https://github.com/petfold/recordstore/blob/main/docs/REFERENCE.md) |
| `mdl-fca` | probabilistic FCA / MDL learning | not a dependency; consumes the same DAG upstream |

## Hard rules

1. **Names are not identifiers.** Object identity is the Swarm content address.
   A filename is a display label (itself just metadata). Never key anything on
   a filename. Never encode paths into names.
2. **Never move or copy bytes to reclassify.** Filing, unfiling, and `mv`
   between concept dirs touch intents only.
3. **No OR in path syntax.** Path concatenation is AND (FCA join). Union =
   list two directories. Do not introduce query operators into paths
   (Tagsistant's `+/`/`@/` syntax is the documented anti-pattern —
   see DESIGN_DECISIONS.md).
4. **Reserved namespaces start with a dot** at mount root: `/.swarm/`,
   `/.unfiled/`, and per-directory `/.all/`. Attribute names must not start
   with `.` — validate on write.
5. **Lazy materialization.** Never enumerate the lattice or extents eagerly.
   Compute directory contents on `ls`/`info`, cache per-concept, invalidate on
   OntoDAG mutation.
6. **Errors map to OSError subclasses** with correct errno (fsspec convention),
   so the FUSE layer translates them properly: unknown attribute in path →
   FileNotFoundError; write with no stamp → PermissionError with a clear
   message; name collision on read → never an error (disambiguation policy
   applies, SPEC.md § Naming).

## Dev environment

- Python ≥ 3.11. `pip install -e ".[test]"`.
- Core deps: `fsspec`, `ontodag`, `swarmfs`. Dev deps: `pytest`,
  `pytest-asyncio`, `hypothesis`.
- Tests must run **without a Bee node and without FUSE installed**: swarmfs is
  exercised through its Memory/mock ChunkStore backend; FUSE integration tests
  are opt-in (`pytest -m fuse`) and skipped by default.
- The one live-node test (`tests/test_live_bee.py`, house convention: skips
  unless `BEE_API` **and** `BEE_BATCH` are set, real purchased batch only) is
  where both Swarm paths go live at once — real BMT refs as object
  identities, classifications in an OntoDAG on the same node, browse/cat/
  range-read plus scorched-earth rehydration from the committed root. First
  passed 2026-08-01 against a Gnosis-mainnet bee 2.8.1 light node. Everything
  else uses FakeSwarmClient (sha256 stand-in refs; internal consistency only).
- Property-based tests (hypothesis) are the preferred style for path-resolution
  invariants — mirror the invariant-test approach used in the `ontodag` repo.

## Key invariants to test (see SPEC.md for the full list)

- Path resolution is order-insensitive: resolve(p) == resolve(permutation(p)).
- Redundant components are harmless: adding an attribute already implied by
  the path's closure does not change resolution.
- Filing then listing round-trips: after `pipe_file('/a/b/x', data)`, the
  object is visible at every concept whose intent ⊆ closure({a,b}) via `.all/`,
  and at its object concept via plain `ls`.
- `rm` at one concept never affects the object's visibility under attributes
  not implied by that classification.
- Same bytes filed twice under different paths = one object, merged intent.

## Reading order for a new session

1. This file.
2. `SPEC.md` — the v0/v0.1 contract, method by method.
3. `DESIGN_DECISIONS.md` — prior art and the decisions already made; do not
   relitigate these without flagging it to Peter.
4. `ROADMAP.md` — what is in scope *now* vs deferred.
