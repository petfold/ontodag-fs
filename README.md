# ontodag-fs

**Browse your knowledge, not your folders.** ontodag-fs presents an
[OntoDAG](https://github.com/petfold/ontodag) category lattice as a real,
mountable filesystem, with file content stored on
[Ethereum Swarm](https://www.ethswarm.org/) via
[swarmfs](https://github.com/petfold/swarmfs).

It is a modern descendant of Gifford's *Semantic File System* (SOSP '91):
directory names are interpreted as **queries**, not locations — but with a
concept lattice instead of flat attributes, and content-addressed storage
instead of a local disk.

```console
$ ontodag-fs tree /
/
├── animal/
│   ├── dog/
│   │   └── rex.txt
│   ├── pet/
│   │   └── rex.txt
│   └── spider/
│       ├── document/
│       │   └── web-study.md
│       └── charlotte.txt
└── document/
    ├── spider/
    │   └── web-study.md
    ├── DESIGN_DECISIONS.md
    └── SPEC.md
```

The same file appears under every path it *belongs* to — `web-study.md` is
both a spider thing and a document, so it lives at `/animal/spider/document/`,
`/document/spider/`, and every reordering of those. No copies, no symlinks:
one object, several true names.

## The ideas in five lines

- **Paths are queries.** `/pet/dog` means "everything that is a pet AND a
  dog". Order never matters: `/dog/pet` is the same place.
- **Directories are concepts.** Subdirectories are the categories that
  meaningfully refine what you're looking at.
- **Files are classified objects.** A file's identity is its Swarm content
  address; its name is just a display label.
- **The ontology does the work.** File something under `dog` and it is
  automatically under `mammal`, `animal`, `pet` — subsumption is free.
- **References cannot dangle.** Content addressing means a classification
  can never point at a file that "moved" — there is nowhere to move to.
  (Tag filesystems on top of paths fight this forever; here it is
  structurally impossible.)

## Quick start

```console
$ pip install git+https://github.com/petfold/ontodag-fs.git
$ ontodag-fs -s swarm:my-store tree /        # browse a Swarm-backed store
$ ontodag-fs -s swarm:my-store cat /pet/dog/rex.txt
$ pip install fusepy && ontodag-fs -s swarm:my-store mount ~/mnt
```

New here? Read the **[User Guide](docs/USER_GUIDE.md)** — a tutorial that
takes you from an empty machine to a mounted, browsable ontology, with
worked examples of every capability.

## Status

**v0 — read-only view.** Browsing (`ls`, `tree`, `cat`, `info`, FUSE mount)
is complete and tested. Filing through the filesystem (`cp` into a concept
directory, `rm` as reclassification, `mv` between concepts) is **v0.1**, in
progress; today filing is done with a short Python helper (see the User
Guide). The lattice itself (creating categories) is edited through OntoDAG's
own API, never through the mount. See [ROADMAP.md](ROADMAP.md).

## Architecture

```
            FUSE mount (fsspec.fuse — a deployment mode, not architecture)
                 │
        OntoDAGFileSystem (this repo: fsspec AbstractFileSystem, stateless glue)
           │                │
        OntoDAG           swarmfs
     (classifier/index)  (bytestore: fsspec backend for Swarm)
           │                │
       recordstore        Bee node
     (persistence of the DAG)
```

This repo owns **no state**: classifications live in OntoDAG, the DAG
persists through recordstore, bytes live on Swarm. `OntoDAGFileSystem` is a
pure [fsspec](https://filesystem-spec.readthedocs.io/) backend, so besides
the CLI and FUSE you also get the whole fsspec ecosystem (pandas, pyarrow,
DuckDB, …) for free.

| Repo | Role |
|---|---|
| [ontodag](https://github.com/petfold/ontodag) | the category DAG — index and classifier |
| [swarmfs](https://github.com/petfold/swarmfs) | fsspec backend for Swarm — the bytestore |
| [recordstore](https://github.com/petfold/recordstore) | versioned key→record store over Swarm — DAG persistence |
| [mdl-fca](https://github.com/petfold/mdl-fca) | MDL/FCA learning over the same DAG (upstream, not a dependency) |

## Documentation

- [User Guide](docs/USER_GUIDE.md) — tutorial, setup, worked examples
- [SPEC.md](SPEC.md) — the precise v0/v0.1 contract, method by method
- [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) — prior art and every decision, with reasoning
- [ROADMAP.md](ROADMAP.md) — what's in scope now vs later

## Development

```console
$ git clone https://github.com/petfold/ontodag-fs && cd ontodag-fs
$ python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
$ .venv/bin/pytest
```

The test suite runs entirely offline — no Bee node, no FUSE — and every
test runs against both the in-memory reference index and the real OntoDAG
adapter, so the two cannot drift apart. Path-resolution invariants are
property-based (hypothesis); see SPEC §6 for the invariant list.
