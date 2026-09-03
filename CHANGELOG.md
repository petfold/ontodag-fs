# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/); versions follow
[Semantic Versioning](https://semver.org/) (0.x: minor bumps may change
behaviour).

Entries before 0.3.0 were back-filled on 2026-08-06 from the release commits —
this file did not exist while its sibling repos (`ontodag`, `recordstore`,
`swarmfs`) each kept one, which made the family's release history unevenly
readable. The design *reasoning* lives in
[DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) and stays there; this is the "what
changed, when" index.

## [0.3.4] — 2026-09-03

### Changed

- **ontodag range is now `>=0.16.0,<0.21.0`** — the ceiling rose because
  ontodag's release gate ran this suite against the 0.20.0 candidate (core
  pack v4: Wikidata as a fourth witness, three sense corrections) and it
  passed unchanged. No code change: 0.20.0 changes the shipped upper
  ontology and nothing this package calls.

## [0.3.3] — 2026-09-02

### Changed

- **ontodag range is now `>=0.16.0,<0.20.0`** — the ceiling rose because
  ontodag's release gate ran this suite against the 0.19.0 candidate (core
  pack v2, `ontodag.act`, the Pyodide demo) and it passed unchanged. No
  code change: 0.19.0 adds surface and moves nothing this package calls.

## [0.3.2] — 2026-08-20

### Changed

- **ontodag range is now `>=0.16.0,<0.19.0`** — the ceiling rose because
  ontodag's release gate ran this suite against the 0.18.0 candidate
  (overlay views, `odag ingest`, merge preview) and it passed unchanged;
  the bump is the acknowledgement, per the standing cross-repo rule.

## [0.3.1] — 2026-08-09

### Changed

- **ontodag range is now `>=0.16.0,<0.18.0`** — the ceiling rose because
  ontodag's release gate ran this suite against both the 0.17.0 and 0.17.1
  candidates and passed, and because it passes here against released 0.17.1
  (286 passed, 1 skipped). No code change: the floor stays at 0.16.0, where a
  *use* put it (`--as-of` calls `Backend.load_at`), while a ceiling records
  what has been *tested*. Nothing in this repo uses 0.17's additions —
  `ontodag.browse`, the packaged web app (`odag web`), or `dispatch`'s
  capturable streams.

  Without this, `pip install ontodag-fs` held ontodag at 0.16.0, so the two
  could not be installed together at their current versions.

## [0.3.0] — 2026-08-06

### Added

- **`--as-of ROOT` browses a past version of the store** — a global flag beside
  `-s`/`--raw`, so `ls`, `tree`, `cat`, `info` and `mount` all show the store as
  it was. Any prefix that `odag history` prints resolves. A version *is* a root,
  so this implements nothing: it hydrates the index from a different one
  (ontodag 0.16.0's `Backend.load_at`), and prefix resolution plus the "this
  store keeps no versions" error come from upstream, so the message matches
  `odag --as-of`'s. It needed no safeguards because this view was already
  read-only — the awkward question elsewhere (what happens if you *write* to
  history?) cannot arise here. Decision record: DESIGN_DECISIONS #22, which also
  names what was deliberately **not** adopted from the same ontodag release and
  why: `move`/`remove --cone`/`undo`/`redo` write (and moving a store's pointer
  from under a live mount would surprise every reader of it), `excerpt`/`diff`
  are file-shaped tools about stores rather than paths, and `overlapping` has no
  path spelling because a candidate set is not a concept (`.maybe/`, a sibling of
  `.all/`, is the shape if it is ever wanted).

### Changed

- **ontodag range is now `>=0.16.0,<0.17.0`.** The ceiling rose because
  ontodag 0.16.0's release gate ran this suite against the candidate and passed;
  the floor rose because `--as-of` uses `Backend.load_at`, new in 0.16.0.

## [0.2.1] — 2026-08-04

- Adopted swarmfs 0.8.0's public raw-reference surface (`read_reference`,
  `reference_size`) in place of reaching past it, and pointed the docs at the
  upstream test-pinned `REFERENCE.md` files.

## [0.2.0] — 2026-08-04

- **Readable value directories**: typed values are shown as
  `ontodag.surface.render` spells them (`weight(4500g)` rather than
  `weight(9/2kg)`), display-only — intents and every comparison stay canonical.
  `--raw` is the switch (DESIGN_DECISIONS #21).
- **Browsing a native `.od` store**, once ontodag persisted node metadata there.
- **Residency-safe `OntoDAGIndex`**, so eager, lazy and sparse DAGs answer
  identically; lazy *mounts* stayed unadopted for the reason recorded in
  ROADMAP.md.
- The ontodag range gained a ceiling, and assertions about what this repo relies
  on upstream (`tests/test_upstream_contract.py`).

## [0.1.0] — 2026-07-31

- **Virtual directories for typed values**: a parametric dimension term is a
  path component (`/weight(..5kg)/`), with no node needing to exist for it.

## [0.0.2] — 2026-07-28

- Packaging and CI normalized across the stack; publishing gated on the test
  suite; BSD-3-Clause metadata.

## [0.0.1] — 2026-07-25

- First release: the fsspec backend (`OntoDAGFileSystem`), the concept-lattice
  path namespace, and the `odag-fs` CLI.
