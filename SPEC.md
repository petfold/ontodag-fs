# SPEC.md — ontodag-fs v0 / v0.1

Status: agreed design, ready to implement. Scope split: **v0 = read-only view**,
**v0.1 = filing (writes)**. Anything not listed here is out of scope (see
ROADMAP.md).

## 1. Data model

- **Attribute**: a globally-named tag (string). The only global namespace.
  Constraint: must not start with `.`, must not contain `/`. (Polysemy —
  e.g. `jaguar` the car vs the animal — is acknowledged and deferred;
  see DESIGN_DECISIONS.md § Deferred.)
- **Concept**: an FCA concept in the OntoDAG lattice — (extent, intent) pair.
- **Terminology caveat** (for FCA-literate readers): "intent", "extent" and
  "closure" are used here in the *implication/subsumption* sense — closure =
  DAG-ancestor completion of an asserted attribute set; extent = the derived
  object set below it. They are NOT the extensional operators of formal
  concept analysis (closure = intent(extent(A)) over the current object
  population): a path's meaning must not depend on what happens to be filed
  today (see DESIGN_DECISIONS #18/#19). Book-FCA remains recoverable — every
  object's ancestor set is its row in the formal context — and inductive FCA
  lives upstream in mdl-fca.
- **Object**: identified by its **Swarm reference** (64/128-char hex). Carries:
  - `intent`: set of attributes (closed under FCA implication when queried),
  - `label`: display filename (metadata, NOT identity),
  - optional provenance attributes (e.g. `import:laptop-2026-07`).
- **Path** = unordered set of attribute constraints. `parse(path)` splits on
  `/`, discards empties, yields a set. Resolution:
  `resolve(path) = concept whose intent is the FCA closure of that set`.
  If no such concept exists in the lattice → FileNotFoundError (ENOENT).
  Order-insensitive and idempotent under redundant components by construction.

## 2. Mount namespace layout

```
/                         top concept (⊤)
/<attr>/.../<attr>/       any concept, reachable by any attribute set
    <subconcept>/         lattice children of the current concept
    <object files>        objects whose OBJECT CONCEPT is exactly here
    .all/                 full extent of this concept, flattened (lazy)
/.swarm/<reference>       raw read-through to Swarm by content address
/.unfiled/                objects known to OntoDAG with empty/retracted intent
```

### Listing policy (the "hybrid" decision)

`ls` of a concept shows:
1. **Directories**: the concept's immediate sub-concepts *given the current
   query* (lattice children), by attribute name. Only attributes that refine
   the current extent (skip attributes yielding an identical or empty extent).
2. **Files** (the coverage rule, DESIGN_DECISIONS #18): every member of the
   extent whose intent contains *no listed child attribute* — i.e. every
   object that none of the shown subdirectories covers. This includes all
   objects whose object concept is this concept, and additionally rescues
   objects stranded by identical-extent child skipping (the dead-end case
   found at the v0 milestone).
3. **`.all/`**: virtual subdirectory materializing the FULL extent (every
   object at or below this concept). Never precomputed; listed on demand.

Rationale: full-extent-everywhere makes `ls /` list the entire store;
object-concept-only makes browsing a scavenger hunt. Hybrid keeps listings
small while keeping everything one `.all/` away. Reachability is universal;
listing is scoped. The coverage rule guarantees the listing *covers* the
extent — everything at or below the concept is either a file here or inside
a shown subdirectory; no dead ends. Consequence: an object's display
position is population-dependent (it surfaces at a browsed ancestor until a
refining sibling makes the child directory appear); its object concept,
reachability, and `.all/` visibility are stable throughout.

### Naming / collision policy

Within any single listing, if an object's `label` is unique → shown as-is.
If two or more objects share a label in the same listing → each is shown as
`{label}~{shorthash}` where shorthash = first 8 hex chars of the Swarm
reference, with the suffix inserted before the extension
(`notes~a1b2c3d4.txt`). Both the plain name (when unique) and the suffixed
form (always) must resolve on lookup. Deterministic: same listing → same names.

## 3. fsspec surface — method by method

Class `OntoDAGFileSystem(AbstractFileSystem)`, protocol `ontodag://`.
Constructor takes an OntoDAG instance/handle and a swarmfs filesystem instance
(dependency injection — enables Memory-backed tests).

### v0 (read-only)

| Method | Behavior |
|---|---|
| `ls(path, detail)` | Resolve path → concept. Return per Listing policy §2. For `/.swarm/<ref>` delegate to swarmfs. For `.all/` return flattened extent. |
| `info(path)` | Concept dir → `{type: directory, name, intent: [...]}`. Object → `{type: file, name, size, swarm_ref, intent: [...]}`. Size comes from swarmfs metadata; fetch lazily. |
| `exists(path)` | resolve() succeeds, or path names an object in the resolved concept's extent, or a valid `/.swarm/` ref. |
| `cat_file(path)` / `open(path,'rb')` | Resolve dirname → concept; match basename per Naming policy → object → stream via `swarmfs.open(ref)`. |
| `isdir` / `isfile` | Directory iff resolves to a concept or reserved namespace; file iff basename matches an object. Note a name can be both an attribute and a label — attribute/concept wins for `isdir`, object wins for `isfile`; document this and test it. |
| `checksum(path)` | The Swarm reference (content address — it IS the checksum). |

Unsupported in v0 (raise NotImplementedError with a one-line reason):
`mkdir`, `rmdir`, `pipe_file`, `put_file`, `rm`, `mv`, `touch`.

### v0.1 (filing)

| Method | Behavior |
|---|---|
| `pipe_file(path, data)` / `put_file(lpath, rpath)` | Split rpath → (attrset, label). Upload bytes via swarmfs → reference. Assert in OntoDAG: object(reference) intent ⊇ closure(attrset); set label. If the reference already exists as an object → **intent union, no re-upload** (dedup by content address). Requires a valid postage stamp via swarmfs config; on missing/expired stamp raise PermissionError("no valid postage stamp — see swarmfs configuration"). |
| `rm(path)` | Resolve to (object, concept-at-path). Retract the classification: intent ← intent minus the attributes asserted by this path that are not implied by the remaining intent. If intent becomes empty → object appears under `/.unfiled/`. NEVER touches bytes. `rm /.unfiled/x` → remove the object from OntoDAG's index entirely (bytes persist on Swarm regardless — say so in the docstring). |
| `mv(src, dst)` | Same object, different concept dirs: retract(src) + assert(dst) atomically w.r.t. the OntoDAG API. Label rename (same dir, new basename): update label only. |
| `cp(src, dst)` within the mount | Alias for assert(dst) — intent union. No bytes move. Cross-filesystem cp (local→mount) is `put_file`. |
| Filing an existing Swarm ref | `pipe_file` variant / CLI: given `/.swarm/<ref>` as source and a concept path as dst → classify WITHOUT uploading. This is the classify-by-reference workflow. |

### Explicitly rejected mappings

- `mkdir` → concept creation: **deferred** (ontology editing through a keyhole;
  underspecified intent). See DESIGN_DECISIONS.md.
- `rmdir` → concept deletion: same, deferred.
- Query operators in paths (OR/NOT): rejected permanently.
- `touch` → empty object: rejected in v0.x (an empty file has one content
  address for ALL empty files — degenerate under content addressing).

## 4. Caching (per the SFS lazy-materialization lesson)

- Per-concept cache of (children, object-concept members), keyed by the
  concept's closed intent. Populated on first `ls`/`lookup`, LRU-bounded.
- `.all/` results cached separately (they're the expensive ones), same key.
- Invalidation: subscribe to OntoDAG mutation events if the API offers them;
  otherwise a mount-level generation counter bumped on every write through
  this layer, plus a TTL (default 30 s) to catch out-of-band DAG edits.
- swarmfs handles byte/metadata caching; do not duplicate it here.

## 5. Tree import (v1, but the spec constrains v0.1 design)

`ontodag-fs import <local-tree> [--provenance TAG]`:
- file → object: bytes via swarmfs (dedup free via content addressing);
  intent = set of ancestor directory names; label = basename.
- directory name → attribute, nothing more. NO structural mirroring.
- every imported object also gets `import:<TAG>` (default: hostname-date) so
  imported vocabulary is quarantined and queryable, and can later be
  merged/renamed/pruned by mdl-fca as a vocabulary-cleanup pass.
- identical content at `a/c` and `b/c` → ONE object, intent {a, b},
  label collision handled by §2 Naming.

## 6. Invariant test list (hypothesis where possible)

1. `resolve(p) == resolve(shuffle(p))` (order-insensitivity).
2. `resolve(p) == resolve(p + [a])` for any `a ∈ closure(p)` (redundancy).
3. File-then-find: after filing under attrset A, object is in `.all/` of every
   concept with intent ⊆ closure(A), in plain `ls` at its object concept, and
   at any browsed ancestor where no listed child covers it (coverage rule).
4. `rm` locality: retracting at path P leaves visibility under any attribute
   set not implied by P's assertion unchanged.
5. Content dedup: filing identical bytes under P1 then P2 yields one object
   with intent closure(P1) ∪ closure(P2).
6. Naming determinism + round-trip: every name shown by `ls` resolves back to
   the same object via `cat`.
7. No-byte-motion: across any sequence of rm/mv/cp within the mount, the set
   of swarmfs upload calls is empty.
8. Reserved-namespace hygiene: attributes beginning with `.` are rejected on
   write; `/.swarm/`, `/.unfiled/`, `.all/` never appear as attributes.
9. Coverage (no dead ends): for every browsable concept C, every member of
   extent(C) is either listed as a file at C or lies in the extent of a
   listed child directory.

## 7. Non-goals (v0.x)

Concept/lattice editing via the mount; OR/NOT queries; xattr exposure
(earmarked v1+ — `getfattr` showing an object's full intent); dedicated
fusepy layer; feeds/mutable references; access control (ACT); any persistence
in this repo.
