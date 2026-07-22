# DESIGN_DECISIONS.md — prior art and settled decisions

This file records decisions already made in design sessions (July 2026,
Peter + Claude). Claude Code: treat these as constraints. If implementation
reveals a genuine conflict, flag it explicitly rather than silently deviating.

## Prior art and what we take from each

**Gifford, Jouvelot, Sheldon, O'Toole — "Semantic File Systems", SOSP '91.**
The direct ancestor: virtual directory names interpreted as queries; attribute
extraction via pluggable "transducers"; implemented as an NFS interposition
layer. We inherit: (a) paths-as-queries, (b) **lazy materialization** — they
computed a virtual directory only when a client readdir/lookup touched it, with
caching and fault-on-stale; we adopt this as SPEC §4, (c) transducers as a
*separable* concern — automatic intent extraction lives upstream of the
filesystem layer (eventually mdl-fca territory), never embedded in it; the
write path is agnostic about whether an intent was asserted by a human drop
or an extraction pipeline. Our deltas over SFS: an FCA **concept lattice**
instead of a flat attribute space (SFS had no notion that one query subsumes
another; we get the ordered hierarchy, closure, and implication for free), and
**content-addressed storage** (Swarm) instead of a local volume, giving a clean
index-vs-bytestore split they didn't have.

**Tagsistant (C, FUSE tag filesystem).** Validates namespace separation between
query space and reserved roots — our `/.swarm/`, `/.unfiled/`, `.all/`.
Negative lesson, adopted as a hard rule: their query operators in path syntax
(`+/`, `@/` for AND/OR) are widely disliked as unreadable. FCA join gives us
AND by concatenation; **OR is deliberately inexpressible in paths** (list two
directories instead).

**TMSU (Go, tag filesystem).** Independently converged on view-not-store: the
virtual FS is a lens, the database only maps tags→paths. Confirms our
stateless-adapter shape. Their chronic pain — dangling references when files
move under the view — is structurally dissolved by content addressing:
Swarm references cannot dangle. State this in the README as a designed
advantage. Their filename-collision handling (ID suffixes) informs our
`label~shorthash` policy.

**BeOS BFS.** Live attribute queries were the feature people remembered for
decades. An extent *is* a live query, so we get the semantics for free; the
lesson we adopt is operational: expose/consume OntoDAG mutation events so
mounted views invalidate promptly (SPEC §4).

**WinFS (cautionary).** Died trying to be the *primary* store with a universal
schema, replacing the filesystem. Every survivor in this lineage is an overlay.
ontodag-fs is an overlay over Swarm and must stay one: it is never
authoritative for anything.

## Settled decisions (with the reasoning, so they aren't relitigated blind)

1. **Separate repo**, not a subpackage of ontodag. Different dependency profile
   (no OS-level FUSE deps near the FCA/MDL core), different test discipline,
   scoped CLAUDE.md, small agent-friendly context. Same modularity pattern as
   the recordstore extraction.
2. **fsspec first, FUSE second.** Pure AbstractFileSystem backend; FUSE is a
   deployment mode via `fsspec.fuse.run`. Buys three interfaces at once
   (Python/fsspec API, FUSE mount, pandas/pyarrow-etc. interop). A dedicated
   fusepy layer only if the generic wrapper proves too crude in practice —
   swap happens above the backend, which doesn't change.
3. **Multi-path DAG projection, no canonical spanning tree.** Every attribute
   set reaching a concept is a valid path. Honest to the DAG; symlink-tree
   projection rejected. Accepted consequences: `du` overcounts, naive recursive
   copy duplicates — this is a semantic view, not a backup target.
4. **Path = unordered attribute set, resolved by FCA closure.** Order-
   insensitive; redundant components harmless; deep paths survive DAG
   refactoring; faceted navigation for free.
5. **Names are labels, not identifiers.** Identity = Swarm content address.
   Dissolves the tree-world `a/c` vs `b/c` problem: two objects, both labeled
   `c`, tagged {a} and {b} — or ONE object with intent {a,b} if the bytes are
   identical. No path-encoding into names, ever.
6. **Hybrid listing policy** (SPEC §2): sub-concepts + object-concept members
   in plain `ls`, full extent behind `.all/`. Full-extent-everywhere is
   unusable at the top of the lattice; object-concept-only breaks browsing
   intuition.
7. **Writes = classification; bytes never move.** cp-in = store + assert;
   rm = retract; mv = retract + assert; cp within mount = intent union.
   Unclassified objects surface in `/.unfiled/`, they don't vanish (Swarm is
   immutable; the mount tells the truth about that).
8. **`mkdir` deferred.** Concept creation through a path string is ontology
   editing through a keyhole — the new concept's intent would be defined
   implicitly and badly. The mount is read-write for object filing, read-only
   for lattice structure, until living with the mount shows what mkdir
   semantics are actually wanted.
9. **Read-through raw namespace `/.swarm/<ref>`** included from v0. ~30 lines
   of delegation; enables classify-by-reference (file existing Swarm content
   without re-upload), which content addressing makes the *correct* filing
   primitive.
10. **Tree import promotes directory names to attributes, quarantined by a
    provenance tag.** Directory names are often junk (`old/`, `tmp/`, `v2/`);
    provenance attributes (`import:<tag>`) keep imported vocabulary queryable
    and separable, and hand the cleanup problem to mdl-fca (attribute
    merge/rename/prune), where it becomes training signal instead of
    contamination.
11. **Stateless adapter.** No databases, no persisted state in this repo.
    OntoDAG owns classification state; recordstore owns DAG persistence;
    swarmfs owns bytes. In-memory caching only.

12. **Object layer: objects are leaf Items named by their Swarm reference**
    (decided 2026-07-22). ontodag's current model is category-only — `Item`
    carries just a name, and identity at the public boundary is the name.
    Objects reuse that machinery: an object is a DAG leaf whose *name is the
    Swarm reference* (so name-identity and content-address-identity coincide,
    satisfying hard rule 1), filed via `put(ref, attrs)`; extents fall out of
    the existing descendant-cone queries. The label and provenance live in a
    small metadata dict to be added to `Item`. Objects are distinguished from
    category leaves by an explicit marker (metadata flag), not by guessing
    from name shape. Rejected alternative: a separate ref→(intent, label)
    registry beside the DAG — cleaner FCA story, but a whole new API and
    recordstore persistence surface for no v0 benefit.
13. **Sequencing: interface-first in this repo, ontodag extension second**
    (decided 2026-07-22). ontodag-fs codes against a minimal Protocol
    (resolve/children/extent/object info) with an in-memory implementation
    that mirrors decision 12's model; the ontodag repo grows the object layer
    in a separate change once the read-only view has validated the interface.
    The Protocol is the dependency-injection seam SPEC §3 already requires
    for testing.

14. **Storage tiers: memory / disk / Swarm; "local" means disk**
    (decided 2026-07-22). Memory is the test/dev tier only (plain in-memory
    OntoDAG, fake Swarm client) and never grows persistence features. The
    real local option is disk: a local bytestore as a content-addressed
    directory, and DAG persistence via a recordstore backend writing to a
    local directory. Hard condition: **a local bytestore must use Swarm's
    own content addressing (BMT references, computable offline via
    swarmfs's bmt.py)** — identity must be location-independent, so moving
    bytes to Swarm later changes no object's identity. A local store keyed
    by any other hash would create a second identity namespace and violate
    hard rule 1. All of this lives in the dependencies (swarmfs,
    recordstore/ontodag), never in this repo.
15. **Flagship DAG configuration: shared base ontology on Swarm + private
    overlay on disk** (decided 2026-07-22). A layered DAG in *ontodag*
    hydrates the shared base read-only, keeps the private DAG on disk
    (same record format, recordstore disk backend), and presents the
    merged view through the same interface — ontodag-fs receives a
    ConceptIndex and never knows it's layered. Write routing: the base is
    immutable through the layer; every mutation (filed objects, new
    attributes/concepts) lands in the overlay. Retracting *base*-asserted
    facts needs whiteout records — **deferred**; overlay-only retraction
    ships first. Base refresh = re-hydrate + re-merge (a rebase); default
    policy for attributes the base dropped: they survive as overlay-local,
    flagged. Amplifies the known polysemy problem slightly; the existing
    answer (provenance tagging + mdl-fca cleanup) applies unchanged.
16. **The dangling-share configuration (shared DAG on Swarm + local-only
    bytes) is avoided by construction, not supported** (decided
    2026-07-22). Private classifications live in the disk overlay next to
    possibly-local bytes — consistent because both are private. The shared
    base only gains assertions through a deliberate publish, and
    **publishing an assertion requires the referenced bytes to be on Swarm
    first** (bytes, then assertion). Nothing shared may ever reference
    unpublished bytes; the TMSU "references cannot dangle" advantage is
    thereby preserved for every reader of the shared DAG, not just the
    author.

## Acknowledged and deferred (named in the spec so they aren't forgotten)

- **Polysemy of attribute names** (`jaguar` car vs animal). FCA context
  usually disambiguates at the concept level; if a genuine split is needed,
  candidate mechanisms are qualified names or MDL-driven attribute splitting
  on bimodal extents. Not a v0 problem; is a named problem.
- **mkdir/rmdir as lattice edits** — revisit post-v1 with usage experience.
- **xattr exposure of intents** (`getfattr -d` → full classification):
  earmarked v1+; POSIX-native home for exactly this metadata; nearly free
  under FUSE.
- **OR/NOT queries**: OR permanently rejected *in path syntax*; a query API
  outside path syntax (CLI or fsspec method) may come later.
