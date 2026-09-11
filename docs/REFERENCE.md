# ontodag-fs Reference

Compact, definition-first, no narrative. The semantics contract — the
*what must hold* — is [SPEC.md](../SPEC.md); design history is
[DESIGN_DECISIONS.md](../DESIGN_DECISIONS.md); the walkthrough is the
[User Guide](USER_GUIDE.md). Dependencies keep their own test-pinned
references: [recordstore](https://github.com/petfold/recordstore/blob/main/docs/REFERENCE.md)
and [swarmfs](https://github.com/petfold/swarmfs/blob/main/docs/REFERENCE.md).
Tables here are pinned against the code by `tests/test_reference.py` — if a
name or parameter in this file and the code disagree, the suite fails.

Package version this file describes: `0.5.0`.

## 1. Vocabulary

| term | definition |
|---|---|
| concept | A directory: the set of objects whose intents cover an unordered attribute set. |
| intent | The attribute set asserted for an object; paths query intents by FCA closure. |
| extent | All objects at or below a concept (`/.all/` flattens it). |
| object | A file. Identity is the Swarm content address; the filename is a display label. |
| label | Display metadata, never an identifier. Colliding labels list as `stem~shorthash.ext`. |
| ref | 64-hex Swarm reference (128 when encrypted) — the object's identity and byte source. |
| generation | The index's change counter; listing caches are generation-checked. |

## 2. Install

| command | gives |
|---|---|
| `pip install ontodag-fs` | the filesystem + `odag-fs` CLI (deps: fsspec, ontodag ≥ 0.16 &lt; 0.24, swarmfs ≥ 0.10.1) |
| `pip install "swarmfs[fuse]"` | optional: `odag-fs mount` via swarmfs's FUSE mounter (needs a system libfuse 2); read-only |

## 3. Exports

Everything importable from `ontodag_fs` (exactly `__all__`):

| name | one line |
|---|---|
| `OntoDAGFileSystem` | the fsspec filesystem (protocol `ontodag`): browse, and file (v0.1) |
| `ConceptIndex` | the index protocol the filesystem consumes |
| `OntoDAGIndex` | ConceptIndex over a real `ontodag.OntoDAG` |
| `InMemoryIndex` | dependency-free ConceptIndex for tests and demos |
| `ObjectInfo` | one classified object: `ref`, `label`, `intent` |
| `UnknownAttributeError` | a path component names no attribute (surfaces as `FileNotFoundError`) |

## 4. `OntoDAGFileSystem`

| member | signature | semantics |
|---|---|---|
| `OntoDAGFileSystem` | `(index, swarm, listing_ttl=30.0, listing_cache_size=1024, render_names=None)` | glue over a `ConceptIndex` and a swarmfs `SwarmFileSystem`. `render_names`: readable typed-value directory names — explicit arg, else `$ONTODAG_SURFACE`, else on. Listing caches are LRU+TTL+generation-checked. |
| `OntoDAGFileSystem.pipe_file` | `(path, value)` | v0.1 filing: store `value` on Swarm through swarmfs (its stamp/redundancy/encryption policy) and classify it at `path` (`/<concepts…>/<label>`, `.all/` files at the concept, `/.unfiled/<label>` stores unclassified). Identical bytes filed twice are one object (intent union). Returns the reference. No usable stamp → `PermissionError` before any upload. |
| `OntoDAGFileSystem.put_file` | `(lpath, rpath)` | local file → `pipe_file`; a directory-shaped `rpath` takes the local basename. |
| `OntoDAGFileSystem.classify` | `(ref, path)` | classify-by-reference: file an existing Swarm reference at `path` without uploading (also `cp_file("/.swarm/<ref>", path)`). A new object takes the basename as label; a known one keeps its label. |
| `OntoDAGFileSystem.rm_file` | `(path)` | retract the object's *asserted* attributes lying in `closure(path)` (DESIGN_DECISIONS #23); refuses (`PermissionError`) when the object is only here by implication, naming where it is filed. Left with none → `/.unfiled/`. `rm /.unfiled/<x>` forgets the object (bytes stay on Swarm). Directories → `IsADirectoryError`. |
| `OntoDAGFileSystem.mv` | `(path1, path2)` | assert `path2`'s concept, then retract `path1`'s minus `closure(path2)`; same concept + new basename = relabel; `/.unfiled/` as either end files or unfiles. One store version. |
| `OntoDAGFileSystem.cp_file` | `(path1, path2)` | within the view: intent union, label unchanged, no bytes move; from `/.swarm/<ref>` (or a path inside a Swarm collection): `classify`. To `/.unfiled/` is refused (that is `mv`). |
| `OntoDAGFileSystem.open` | `(path, mode="rb")` | `"rb"`: ranged reads; `"wb"`: buffers and `pipe_file`s on close. |

The rest of the surface is fsspec's standard read API (`ls`, `info`,
`cat`, `open`, `isdir`, `isfile`, `exists`, `find`, …) over the namespace
below; every write method raises `NotImplementedError` in v0 (filing lands
in v0.1). Bytes are fetched from Swarm through swarmfs's public
`read_reference`/`reference_size` (0.8.0+), so its verification policy and
local-first mode apply.

## 5. Path namespace (SPEC §2)

| path | meaning |
|---|---|
| `/<attrs...>/` | concept: unordered attribute-set query, resolved by FCA closure |
| `/<attrs...>/.all/` | the concept's full extent, flattened |
| `/.swarm/<ref>` | raw read-through by content address (`ls` of `/.swarm` is `[]` — not enumerable) |
| `/.swarm/<ref>/<sub>` | manifest read-through, delegated to swarmfs |
| `/.unfiled/` | objects with empty or retracted intent |

Naming rules: unique labels are shown as-is; colliding labels as
`{stem}~{shorthash}{ext}` (hash extended on collision). Components are
percent-encoded where they are DAG names; `/.swarm/` components pass
through untouched. A name that is both an attribute and an object label
resolves as the attribute for `isdir`/`info`/`ls` and as the object for
`isfile`/`cat`/`open`.

## 6. `ConceptIndex` (the protocol)

| member | semantics |
|---|---|
| `ConceptIndex.closure` | attribute set → its FCA closure (the concept's intent) |
| `ConceptIndex.children` | child attributes of a concept (the sub-directories) |
| `ConceptIndex.extent` | all objects covered by an intent |
| `ConceptIndex.objects_at` | objects exactly at a concept |
| `ConceptIndex.get_object` | look one object up by ref |
| `ConceptIndex.unfiled` | the `/.unfiled/` population |
| `ConceptIndex.generation` | change counter for cache invalidation |
| `ConceptIndex.display_name` | canonical attribute name → rendered spelling (`render_names`) |
| `ConceptIndex.add_object` | file a ref under attributes (known ref: intent union; non-empty label replaces) |
| `ConceptIndex.asserted` | the *asserted* (direct) attributes of an object — not their closure |
| `ConceptIndex.retract` | drop asserted attributes; none left → unfiled, never deleted |
| `ConceptIndex.relabel` | change the display label only |
| `ConceptIndex.remove_object` | forget a ref entirely (Swarm keeps the bytes) |
| `ConceptIndex.persist` | make mutations durable if the store needs telling (EagerOntoDAG: one commit); the filesystem calls it once per write |

## 7. CLI

`odag-fs [-s STORE] [--bee-api URL] [--as-of ROOT] [--raw] [COMMAND [args]]`
— commands `ls`, `tree`, `cat`, `info`, `cd`, `pwd`, `mount`, `set`, `help`;
no command = pipe or interactive prompt. Store specs and `~/.ontodag/config`
keys (`store`, `bee_api`, `bee_batch`) are shared with `odag`.

`--as-of ROOT` browses a **past version** of the store — any prefix that
`odag history` prints. Needs a store that keeps versions (`rs:PATH` or
`swarm:NAME`); a `.od` file holds one state and says so. Nothing else about
the view changes, since it is read-only either way.

## 8. Errors

| raised | when |
|---|---|
| `FileNotFoundError` | unknown attribute or unresolvable object name (fsspec semantics). |
| `NotImplementedError` | deferred lattice editing (`mkdir`/`rmdir`), `touch`, `open` modes other than rb/wb. |
| `PermissionError` | filing without a usable postage stamp; `rm`/`mv` retracting by implication (#23); writing under `/.swarm/`; `cp` to `/.unfiled/`. |
| `IsADirectoryError` | a write verb aimed at a concept or `.all/` (the lattice is not edited here). |
| `UnknownAttributeError` | index-level: a component names no attribute (callers see `FileNotFoundError`). |
