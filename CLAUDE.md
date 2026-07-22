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
| `ontodag` | Concept DAG, FCA/MDL core | dependency — the index/classifier |
| `swarmfs` | fsspec backend for Swarm | dependency — the bytestore |
| `recordstore` | versioned key→record store over Swarm | indirect (via ontodag persistence) |
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

- Python ≥ 3.11. `pip install -e ".[dev]"`.
- Core deps: `fsspec`, `ontodag`, `swarmfs`. Dev deps: `pytest`,
  `pytest-asyncio`, `hypothesis`.
- Tests must run **without a Bee node and without FUSE installed**: swarmfs is
  exercised through its Memory/mock ChunkStore backend; FUSE integration tests
  are opt-in (`pytest -m fuse`) and skipped by default.
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
