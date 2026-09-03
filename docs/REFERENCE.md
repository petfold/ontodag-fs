# ontodag-fs Reference

Compact, definition-first, no narrative. The semantics contract — the
*what must hold* — is [SPEC.md](../SPEC.md); design history is
[DESIGN_DECISIONS.md](../DESIGN_DECISIONS.md); the walkthrough is the
[User Guide](USER_GUIDE.md). Dependencies keep their own test-pinned
references: [recordstore](https://github.com/petfold/recordstore/blob/main/docs/REFERENCE.md)
and [swarmfs](https://github.com/petfold/swarmfs/blob/main/docs/REFERENCE.md).
Tables here are pinned against the code by `tests/test_reference.py` — if a
name or parameter in this file and the code disagree, the suite fails.

Package version this file describes: `0.3.7`.

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
| `pip install ontodag-fs` | the filesystem + `odag-fs` CLI (deps: fsspec, ontodag ≥ 0.16 &lt; 0.18, swarmfs ≥ 0.8) |
| `pip install fusepy` | optional: `odag-fs mount` via fsspec's FUSE wrapper |

## 3. Exports

Everything importable from `ontodag_fs` (exactly `__all__`):

| name | one line |
|---|---|
| `OntoDAGFileSystem` | the fsspec filesystem (protocol `ontodag`, read-only in v0) |
| `ConceptIndex` | the index protocol the filesystem consumes |
| `OntoDAGIndex` | ConceptIndex over a real `ontodag.OntoDAG` |
| `InMemoryIndex` | dependency-free ConceptIndex for tests and demos |
| `ObjectInfo` | one classified object: `ref`, `label`, `intent` |
| `UnknownAttributeError` | a path component names no attribute (surfaces as `FileNotFoundError`) |

## 4. `OntoDAGFileSystem`

| member | signature | semantics |
|---|---|---|
| `OntoDAGFileSystem` | `(index, swarm, listing_ttl=30.0, listing_cache_size=1024, render_names=None)` | glue over a `ConceptIndex` and a swarmfs `SwarmFileSystem`. `render_names`: readable typed-value directory names — explicit arg, else `$ONTODAG_SURFACE`, else on. Listing caches are LRU+TTL+generation-checked. |

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
| `NotImplementedError` | any write in v0 (`_V01` message), or deferred lattice editing. |
| `UnknownAttributeError` | index-level: a component names no attribute (callers see `FileNotFoundError`). |
