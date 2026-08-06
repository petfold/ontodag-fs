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

17. **Node `payload` is for category-attached content; objects don't use it**
    (decided 2026-07-22). ontodag's node records carry a per-node `payload`
    Swarm ref, which predates ontodag-fs. Under decision #12 an object
    node's *name* is its Swarm reference, making `payload` redundant for
    objects — `OntoDAGIndex` ignores it. It is deliberately retained (not
    deprecated) for the other case: content attached to a *category* (e.g.
    a concept's descriptive document), a plausible future feature that is
    already persisted and tested upstream. No byte-storage duplication
    exists in the cluster: recordstore persists the graph (index on
    Swarm), swarmfs stores object bytes (bytestore on Swarm) — the only
    overlap is two Bee HTTP clients at the transport layer, consolidation
    of which would be an upstream refactor invisible to this repo.

18. **The coverage rule for plain listings** (decided 2026-07-22, adopting
    the recommendation under "Dead-end directories" below). Listing rule 2
    becomes: files at concept C = members of extent(C) whose intent
    contains no listed child attribute — the listing must *cover* the
    extent (everything at or below C is a shown file or inside a shown
    subdirectory). Fixes the milestone's dead-end case only; object-concept
    members list exactly as before; coverage test is `o.intent ∩
    shown_children ≠ ∅` (no extra queries); resolution and (future) write
    semantics untouched. Accepted trade-off: display position of an object
    is population-dependent; object concept, reachability, and `.all/` are
    stable. SPEC §2 rule 2, invariant 3, and new invariant 9 updated.
19. **FCA terminology posture** (recorded 2026-07-22, raised by Peter).
    "Intent"/"extent"/"closure" throughout these docs are the
    implication/subsumption versions — closure is DAG-ancestor completion
    of asserted attributes; extents are derived object sets — NOT the
    extensional operators of formal concept analysis (intent(extent(A))
    over the current population). This is deliberate: extensional closure
    would make a path's meaning depend on today's data and would poison
    write-time assertion (#18's analysis, option (a)). The borrowing is
    acknowledged as potentially confusing to FCA-literate readers and is
    flagged in SPEC §1; renaming (e.g. "ascription"/"membership") was
    considered and deferred — revisit if outside contributors stumble.
    Book-FCA stays recoverable (an object's ancestor set is its row in the
    formal context); inductive FCA is mdl-fca's territory, upstream.

20. **Path components are percent-encoded** (decided 2026-08-03, forced by
    ontodag registry 3.0). Canonical typed values became reduced rationals of
    the SI anchor, so `weight(4.5kg)` is stored as `weight(9/2kg)` — a name
    holding the one character a POSIX path component cannot carry. `ls`
    duly emitted a directory entry that the same filesystem's `isdir` and `ls`
    denied. Three options were weighed:

    (a) *Enforce the old rule* — refuse to file a value whose canonical name
    contains `/`. Faithful to SPEC §1 as written and a tiny diff, but it makes
    an ordinary 4.5 kg parcel unfileable, reversing a capability ontodag
    deliberately added (exact rationals, nothing refused for precision).
    Rejected: the filesystem does not get to veto the index's arithmetic.

    (b) *Percent-encode path components* — chosen. `%`→`%25`, `/`→`%2F`,
    NUL→`%00`; decode on lookup. One mechanism, reversible
    (`decode(encode(s)) == s`, the same shape as ontodag's
    `elaborate(render(t)) == t`), and it closes the whole class rather than
    the rational case: object **labels** could always contain `/` — they are
    display metadata, never validated (#5) — which was a latent form of the
    same bug. Every name free of `%` and `/` encodes to itself, so no path
    that resolved before resolves differently.

    (c) *Decimal display when the rational terminates*, encoding otherwise.
    Prettiest listings, but two mechanisms, and the shown form would be
    neither ontodag's canonical name nor its `surface.render` output — this
    repo would own a third naming form. Deferred, not rejected: it becomes
    reasonable if and when `ontodag.surface` is adopted as a display layer
    (ROADMAP), and then it should follow `render`, not invent a form.

    Consequences. Attribute *assertion* keeps the stricter rule (asserted
    names must still be `/`-free — human-chosen vocabulary should stay
    path-clean); only computed names and labels rely on the encoding. Entry
    `name` fields are encoded because they are paths; `label` and `intent`
    fields stay raw because they are data. `/.swarm/` components address
    swarmfs's namespace, not the DAG's, and are passed through untouched.
    Decoding is strict — only the three triplets — so a raw name typed into a
    path still resolves (`/100%`), at the price of one acknowledged ambiguity:
    a name that itself contains a percent triplet resolves in favour of the
    encoded reading. The general lesson is ontodag's own, from its 0.10.1
    post-mortem: the canonical-name grammar fans out into consumers with
    separate escaping rules, and this repo is one of them. That fan-out is now
    a test (`tests/test_names.py`), not a memory.

21. **Listings render, storage stays canonical** (decided 2026-08-03, adopting
    `ontodag.surface`). Directory names for typed values are shown as ontodag's
    surface layer spells them: `time(2026-08)` rather than the instant range,
    `weight(4500g)` rather than `weight(9/2kg)`. Three things made this cheap
    and safe, and they are the reason to prefer it over inventing a display
    form here (#20's option (c)):

    - **Rendering only picks spellings the grammar already accepts.** So a
      shown name resolves through the existing sugar path — `closure()` is
      untouched and `elaborate()` is never called on this side. Display became
      a one-line change at the point where entry names are built.
    - **It is a pure function of the canonical name plus the declarations that
      give it a kind**, which means it needs the DAG. That is why it sits
      behind the ConceptIndex seam as `display_name` (#13) rather than in
      fs.py: `InMemoryIndex` returns identity, so the two implementations stay
      interchangeable.
    - **It is lossy in the harmless direction.** `elaborate(render(t)) == t`
      holds; `render(elaborate(s)) == s` is deliberately not promised. So
      rendered names may never be stored or compared: intents, the coverage
      rule and the disambiguator all stay on canonical names. A rendered name
      in an intent would silently stop matching the DAG.

    Rendering runs *before* encoding, and mostly retires it: the common
    rationals become whole numbers of a smaller unit. `length(10/33m)` is the
    case that proves both layers are needed — no unit makes it whole, so it
    reaches the path as `length(10%2F33m)`.

    Per ontodag's SURFACE_LAYER.md §7 ("one tool with an honest switch") the
    behaviour is switchable: `render_names=` on the constructor, else
    `$ONTODAG_SURFACE` (the same variable odag reads, `0` = off), else on — a
    mount has no tty to test and is only ever read by humans, so ontodag's
    `auto` means on here. `odag-fs --raw` is the CLI face of it. Note the
    consequence for `info()`: it follows §7's Web/REST guidance rather than its
    CLI guidance — the entry `name` is rendered because it is a path, while
    `intent` stays canonical because it is data. Both are always present.

    One limitation this surfaced, recorded rather than fixed: because asserted
    attribute names must stay `/`-free (#20), a value can be *filed* only in a
    spelling without a slash. `weight(4.5kg)` works and stores as
    `weight(9/2kg)`; `weight(1/3kg)` cannot be asserted through this repo's
    builder at all, though it browses and resolves fine once ontodag puts it
    there. That is consistent with the repo not editing the lattice, so it has
    not been treated as a bug — revisit if filing by rational spelling is ever
    wanted.

22. **Browsing a past version is a flag, not a mode** (decided 2026-08-06,
    adopting ontodag 0.16.0's `--as-of`). `odag-fs --as-of ROOT` hydrates the
    index from a named past root instead of the store's current one, and
    everything else — `ls`, `tree`, `cat`, `info`, `mount` — is unchanged.

    Three reasons it stays this small. **A version is a root**, so time travel
    is not a feature to implement but a different value to hydrate from
    (ontodag's `Backend.load_at`, whose prefix resolution and "this store keeps
    no versions" error we inherit verbatim, so the message matches `odag`'s).
    **This view is already read-only**, so a past version needs no extra
    safeguards — the awkward part of undo elsewhere (what happens if you write
    to history?) does not exist here. And **a flag composes with everything**
    where a mode would multiply: `--as-of X mount ~/mnt` gives a mount of
    yesterday for free.

    What was deliberately *not* adopted from the same ontodag release, so the
    question isn't reopened without new information: `move`, `remove --cone`,
    `undo` and `redo` all **write**, and this repo asserts classifications
    rather than performing store surgery — moving the store's pointer from
    under a live mount would surprise every reader of it, which is a
    coordination problem no filesystem should invent. `excerpt` and `diff` are
    file-shaped tools *about stores*, and this surface's unit is a path.
    `overlapping` is the interesting one: a candidate set is genuinely useful
    but is **not a concept**, so it has no path spelling — the shape would be a
    reserved sibling of `.all/` (a `.maybe/`), and nobody has designed its
    semantics (does it recurse? do its children partition?). Left unbuilt with
    the shape named.

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
- **Dead-end directories from mixing the two closures** (surfaced by the
  v0 manual milestone, 2026-07-22; analysis expanded same day). With
  rex.txt filed under `dog ⊂ {animal, pet}` as the only pet,
  `/animal/pet/` lists nothing but `.all/`: the `dog` child is skipped
  (identical extent), and rex is not an object-concept member of
  `{animal, pet}` under implication-closure (his concept adds `dog`).

  Root cause: two closure operators disagree exactly when data is thin.
  *Implication closure* (DAG ancestors) is what the ontology asserts —
  stable under filing; it is what `closure()` implements and the right
  basis for paths-as-assertions and (v0.1) writes. *Formal FCA closure*
  (`intent(extent(A))`) is what the current population exhibits — under
  it, `{animal, pet}` closes to `{animal, pet, dog}` (same formal
  concept) and rex would be listed. The listing policy prunes
  directories *extensionally* (identical-extent skip) but admits files
  *intensionally* (closed-intent equality); the dead end is the gap
  between the two, and it fires whenever `extent(A) = extent(A ∪ {b})`
  for unimplied `b` — i.e., in locally homogeneous data, the dominant
  regime for young and personal ontologies.

  Options weighed: (a) extensional closure for resolution — FCA-pure and
  matches SPEC §1's letter, but rejected: it would poison the write path
  (filing a goldfish at `/pet` while all pets are dogs would assert
  `dog`), or force split read/write path semantics; shown intents would
  also fluctuate with the population. (b) stop skipping identical-extent
  children — no dead ends, purely a listing change, but re-creates the
  one-child corridor noise (`/photo/raw/2026/…`) the hybrid policy
  exists to avoid. (c) **coverage rule — RECOMMENDED**: keep directories
  as they are; redefine listing rule 2 as *files at C = members of
  extent(C) whose intent contains no listed child attribute* (i.e., the
  listing must cover the extent: everything at or below C is inside a
  shown subdirectory or a file right here). Fixes exactly the
  pathological case and nothing else; object-concept members remain
  listed as today; coverage test is `o.intent ∩ shown_children ≠ ∅` (no
  extra extent queries; `children()` already enumerates the extent);
  write-path semantics untouched. Trade-off accepted: an object's
  *display position* is population-dependent (rex shows at `/animal/pet`
  until a cat is filed and `dog/` starts refining) — correct for a live
  view; reachability, object concept, and `.all/` are stable throughout.
  Adopting (c) requires: SPEC §2 rule-2 rewording, invariant-3 rewording
  ("at its object concept, and at any browsed ancestor where no listed
  child covers it"), and a new coverage invariant in SPEC §6 (for every
  browsable concept C, every member of extent(C) is either listed at C
  or in the extent of a listed child). Status: **adopted as decision #18**
  (2026-07-22); SPEC updated, implemented in fs.py's concept listing.

  Related but distinct (not fixed by any option above, deliberately
  open): categories with **no objects at all** are invisible everywhere
  (children require non-empty extents) — whether the mount should show
  vocabulary or only content, judge after browsing a fuller ontology.
