# Kickoff prompt for Claude Code

Paste the following as the first message in a Claude Code session started in an
empty `ontodag-fs` directory containing CLAUDE.md, SPEC.md,
DESIGN_DECISIONS.md, ROADMAP.md (this handoff package).

---

Read CLAUDE.md, then SPEC.md, then DESIGN_DECISIONS.md, then ROADMAP.md, in
that order, before writing anything. These documents are the settled design;
do not relitigate decisions recorded in DESIGN_DECISIONS.md — if you hit a
genuine conflict during implementation, stop and flag it.

Context you'll need from sibling repos (read, don't modify):
- `../ontodag` — the concept DAG API you'll depend on. Identify the minimal
  interface ontodag-fs needs (resolve/closure of an attribute set to a concept;
  a concept's lattice children; extent and object-concept membership; assert /
  retract object classification; object label get/set; mutation notification
  if any). If the current OntoDAG API doesn't cleanly expose one of these,
  write the adapter around what exists and list the gaps in a GAPS.md for
  Peter rather than reaching into OntoDAG internals.
- `../swarmfs` — the fsspec Swarm backend used as the bytestore. Use its
  public SwarmClient/filesystem surface only, dependency-injected.

Then execute ROADMAP step by step:

1. **Step 0 (in ../swarmfs):** the fsspec-FUSE mount deliverables exactly as
   listed in ROADMAP.md Step 0. Small, self-contained; do it first — it
   de-risks the mount path and may surface swarmfs conformance fixes v0
   depends on. Commit in swarmfs on a branch `fuse-mount`.
2. **v0 (in this repo):** scaffold the package (pyproject, src layout,
   `pytest` + `hypothesis`, ruff config consistent with the ontodag repo),
   then implement the read-only OntoDAGFileSystem per SPEC §2–§4, with
   invariant tests 1, 2, 6, 8 from SPEC §6 as property-based tests. All tests
   must pass with in-memory backends only — no Bee node, no libfuse.
3. Stop after v0 and report: what works, what OntoDAG API gaps you found,
   and anything in the spec that implementation pressure suggests revisiting.
   Do not start v0.1 in the same run.

Working agreements: small commits with imperative messages; every public
method gets a docstring stating its OntoDAG/swarmfs delegation per SPEC §3;
raise OSError subclasses per CLAUDE.md rule 6; never add persisted state to
this repo.
