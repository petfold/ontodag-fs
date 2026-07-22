# ontodag-fs User Guide

*A tutorial for people who want to browse their files by what they **are**,
not by where they were put.*

---

## 1. What is this?

Every folder tree forces one question you can never answer well: *where does
this file go?* A tiramisu recipe is a dessert **and** it's Italian — a folder
tree makes you pick one home and lose the other (or make copies, or scatter
symlinks that rot).

ontodag-fs dissolves the question. Files are **classified**, not placed. You
say what something *is* — `{dessert, italian}` — and the filesystem shows it
at every path that fits:

```
/dessert/italian/tiramisu.md      ← works
/italian/dessert/tiramisu.md      ← same file, same place
/recipe/tiramisu.md               ← also there: desserts are recipes
```

There is exactly **one** copy of the file. Directory paths are *queries*
("everything that is a dessert AND Italian"), and the categories live in an
**ontology** — a little knowledge graph called OntoDAG that knows, for
example, that every `dessert` is a `recipe`. The file bytes live on
**Ethereum Swarm**, addressed by their content, which is why nothing can
ever be a broken link: a file's address *is* its content.

You get a normal-looking filesystem out of it — `ls`, `cat`, a real mount
you can point any application at — plus a Python API compatible with the
whole [fsspec](https://filesystem-spec.readthedocs.io/) data ecosystem.

### The mental model, in four sentences

1. **A category** is a named tag that can have parent categories
   (`dessert` is a kind of `recipe`).
2. **A path is a set of categories** — unordered, and anything they imply
   comes free (`/dessert` already means "recipes").
3. **A file is content + a classification + a display name.** Its identity
   is the content address; the name is just a label.
4. **Directories show refinements**: subdirectories are categories that
   narrow down what you're looking at; the special `.all/` shows everything
   at or below the current query, flat.

---

## 2. Setting up

### What you need

- **Python 3.11+**
- **A Bee node** (Swarm's client) for real use — a local node is best:
  see the [Bee quick start](https://docs.ethswarm.org/docs/bee/installation/quick-start).
  It serves the API on `http://localhost:1633` by default.
- **A postage stamp** — Swarm's prepaid storage. Needed only for *writing*;
  browsing/reading needs none. Buy one with
  `curl -X POST http://localhost:1633/stamps/100000000/20` or via
  [swarm-cli](https://github.com/ethersphere/swarm-cli), then note its
  `batchID`.

### Install

Everything installs from GitHub in one command:

```console
$ pip install \
    "ontodag[swarm] @ git+https://github.com/petfold/ontodag.git" \
    "swarmfs @ git+https://github.com/petfold/swarmfs.git" \
    "ontodag-fs @ git+https://github.com/petfold/ontodag-fs.git"
```

This gives you three commands: `odag` (edit the ontology), `odag-fs` (browse it as a filesystem), and — after `pip install fusepy` — the ability
to FUSE-mount it.

Tell the tools where Bee is (only needed if not the default):

```console
$ export BEE_API=http://localhost:1633
$ export BEE_BATCH=<your-stamp-batchID>       # for writes
```

---

## 3. Tutorial: from zero to a mounted ontology

We'll build a small recipe collection. Fifteen minutes, start to finish.

### Step 1 — create the categories

Categories are edited with **odag**, OntoDAG's own CLI (the filesystem view
never edits the ontology — deliberate separation of powers). First point
odag at a named, Swarm-backed store:

```console
$ odag set store swarm:recipes
```

`odag` and `odag-fs` share this setting (one config, `~/.ontodag/config`),
so every command in the rest of this guide — editing *and* browsing —
needs no store flag. (`odag-fs set store …` works identically; a one-off
override is `-s STORE`; with nothing configured, both default to a local
store in `~/.ontodag`.)

Now build a little category tree. `odag put child parent1 parent2 ...`;
no parents means top-level:

```console
$ odag put recipe
$ odag put dessert recipe
$ odag put main recipe
$ odag put italian
$ odag put japanese
$ odag put vegetarian
```

Notice `dessert` has parent `recipe`, while `italian` and `vegetarian` are
independent *facets* — categories don't have to form one tree, and files
will combine them freely. Check your work:

```console
$ odag show
```

### Step 2 — file some recipes

Filing through the filesystem itself (`cp` into a directory) arrives in
v0.1. Today, filing is a short Python helper — save this as `file_it.py`:

```python
#!/usr/bin/env python3
"""file_it.py — file documents into a swarm-backed ontodag store.

usage: python3 file_it.py STORE_NAME FILE CATEGORY [CATEGORY...]
"""
import os
import sys

from fsspec.asyn import sync
from ontodag.swarm_adapter import SwarmOntoDAG
from recordstore import BeeBytesStore, FilePointer, RecordStore
from swarmfs import SwarmFileSystem
from ontodag_fs import OntoDAGIndex

API = os.environ.get("BEE_API", "http://localhost:1633")
BATCH = os.environ["BEE_BATCH"]  # a usable postage stamp

store_name, path, *categories = sys.argv[1:]
pointer = FilePointer(os.path.expanduser(f"~/.ontodag/{store_name}.root"))
dag = SwarmOntoDAG(RecordStore(BeeBytesStore(API, BATCH), pointer=pointer))
index = OntoDAGIndex(dag)
swarm = SwarmFileSystem(api_url=API)

with open(path, "rb") as fh:
    data = fh.read()
ref = sync(swarm.loop, swarm.client.bytes_post, data, BATCH)  # bytes -> Swarm
index.add_object(ref, os.path.basename(path), set(categories))  # classify
dag.commit()  # persist the DAG itself to Swarm
print(f"filed {path} as {sorted(categories)} -> {ref}")
```

File four recipes:

```console
$ python3 file_it.py recipes tiramisu.md dessert italian
$ python3 file_it.py recipes ramen.md    main japanese
$ python3 file_it.py recipes caprese.md  main italian vegetarian
$ python3 file_it.py recipes brownie.md  dessert vegetarian
```

### Step 3 — browse

```console
$ odag-fs tree /
/
├── .all/
├── .swarm/
├── .unfiled/
├── dessert/
│   ├── .all/
│   ├── italian/
│   │   ├── .all/
│   │   └── tiramisu.md  [60799ec6]
│   └── vegetarian/
│       ├── .all/
│       └── brownie.md  [d4e99282]
├── italian/
│   ├── .all/
│   ├── dessert/
│   │   ├── .all/
│   │   └── tiramisu.md  [60799ec6]
│   ├── main/
│   │   ├── .all/
│   │   └── caprese.md  [8fb38b67]
│   └── vegetarian/
│       ├── .all/
│       └── caprese.md  [8fb38b67]
├── main/
│   ├── .all/
│   ├── italian/
│   │   ├── .all/
│   │   └── caprese.md  [8fb38b67]
│   ├── japanese/
│   │   ├── .all/
│   │   └── ramen.md  [c76d8637]
│   └── vegetarian/
│       ├── .all/
│       └── caprese.md  [8fb38b67]
└── vegetarian/
    ├── .all/
    ├── dessert/
    │   ├── .all/
    │   └── brownie.md  [d4e99282]
    ├── italian/
    │   ├── .all/
    │   └── caprese.md  [8fb38b67]
    └── main/
        ├── .all/
        └── caprese.md  [8fb38b67]
```

(This is real output. Your content hashes will match your files.)

Two things worth noticing already. `caprese.md` genuinely appears in six
places — one object, six true names. And there is **no `recipe/` at the
root, and no `japanese/` either**: *everything* you filed is a recipe, so
`recipe` wouldn't narrow anything at the top (it shows up deeper, where it
does help), and the only Japanese thing is a main course, so `japanese/`
lives inside `main/`. Directories are offered where they *refine* — more on
this in §5.

(Prefer a prompt over one-shot commands? Run bare `odag-fs` for an
interactive shell with `cd`/`ls`/`cat` and relative paths — see §4.)

Read a file, ask about a directory or a file:

```console
$ odag-fs cat /italian/dessert/tiramisu.md
$ odag-fs info /vegetarian/main
name: /vegetarian/main
size: 0
type: directory
intent: ['main', 'recipe', 'vegetarian']

$ odag-fs info /vegetarian/main/caprese.md
name: /vegetarian/main/caprese.md
size: 73
type: file
swarm_ref: 8fb38b67cbd9d425d74cfcc5ca1a11b8addd9dbef6c9232cdd18aa94456142cb
label: caprese.md
intent: ['italian', 'main', 'recipe', 'vegetarian']
```

`intent` is the file's full classification — including the implied
`recipe`, which you never typed: the ontology knew `main` is a `recipe`.

### Step 4 — mount it

```console
$ pip install fusepy
$ mkdir -p ~/recipes
$ odag-fs mount ~/recipes
```

In another terminal it's now just a filesystem — use anything:

```console
$ ls ~/recipes/italian/
dessert  main  .all
$ cat ~/recipes/vegetarian/italian/caprese.md
$ grep -ri mascarpone ~/recipes/dessert/.all/
```

Unmount with `Ctrl-C` or `fusermount -u ~/recipes`.

---

## 4. What it can do — worked examples

### One file, every true name

`caprese.md` was filed as `{main, italian, vegetarian}`. All of these work,
and they are all the same single object:

```console
$ odag-fs cat /italian/vegetarian/caprese.md
$ odag-fs cat /vegetarian/italian/caprese.md   # order-free
$ odag-fs cat /recipe/caprese.md               # implied parent
$ odag-fs cat /main/vegetarian/italian/recipe/caprese.md  # redundancy is harmless
```

### Narrowing: paths are AND-queries

Each path segment narrows the result. Where does the vegetarian Italian
food live? Just say so:

```console
$ odag-fs ls /italian/vegetarian
.all/
caprese.md
```

There is deliberately **no OR** in paths — "Italian or Japanese" is two
`ls` calls, not one weird path syntax.

### `.all/` — everything below here, flat

Plain listings stay tidy: they show refining subdirectories, and files that
belong exactly at the current level. When you want *everything at or below*
a query — for a search, a backup, a batch job — every directory has `.all/`:

```console
$ odag-fs ls /recipe/.all
brownie.md  caprese.md  ramen.md  tiramisu.md
$ grep -l basil ~/recipes/.all/*            # the whole store, one flat dir
```

### Two files, one name — no problem

Names are labels, not identities, so nothing stops two files both being
called `notes.md`:

```console
$ echo "shopping: mascarpone, savoiardi" > notes.md
$ python3 file_it.py recipes notes.md italian
$ echo "shopping: chashu, nori, mirin" > notes.md
$ python3 file_it.py recipes notes.md japanese
```

Where the two meet in the same listing, each gets a short content-hash
suffix — deterministic, and always resolvable:

```console
$ odag-fs ls /.all
brownie.md
caprese.md
notes~22bc67dd.md
notes~d3eae922.md
pasta.md
ramen.md
tiramisu.md
$ odag-fs cat /.all/notes~22bc67dd.md
shopping: mascarpone, savoiardi
```

Where a name is unambiguous, it stays plain:

```console
$ odag-fs ls /japanese     # only one notes.md here
.all/
main/
recipe/
notes.md
```

### Same content twice = one object

File the identical bytes under two different classifications and you don't
get two files — you get **one object with the merged classification**.
Content addressing makes deduplication automatic:

```console
$ python3 file_it.py recipes pasta.md italian
filed pasta.md as ['italian'] -> a96276cc24bbeaae…
$ python3 file_it.py recipes pasta.md vegetarian     # same bytes!
filed pasta.md as ['vegetarian'] -> a96276cc24bbeaae…    # same reference
$ odag-fs info /italian/pasta.md | grep intent
intent: ['italian', 'vegetarian']                    # one object, both facets
```

### Raw access by content address

Every file's true identity is its Swarm reference — visible as `swarm_ref`
in `info`, and usable directly through the `/.swarm/` namespace, even for
content nobody has classified yet:

```console
$ odag-fs info /japanese/ramen.md | grep swarm_ref
swarm_ref: c76d86370de23d5f…               # this IS the file's checksum
$ odag-fs cat /.swarm/c76d86370de23d5f…<full 64 hex>
# Shoyu Ramen
…
```

Share the reference with anyone on Swarm and they have the file — the
classification is yours; the content is simply *addressable*.

### The lost-and-found: `/.unfiled/`

Objects the ontology knows about but that currently have no categories
(freshly registered, or fully retracted in v0.1) don't vanish — they wait
in `/.unfiled/` until you classify them.

### An interactive shell for the lattice

Run `odag-fs` with no command and you get odag's interactive convention —
a `>` prompt — plus a *current directory*, so paths can be relative and
the store loads only once for the whole session:

```console
$ odag-fs
odag-fs 0.0.1 - type help for help
> cd italian
/italian> ls
.all/
notes.md
recipe/
vegetarian/
/italian> cat dessert/tiramisu.md
# Tiramisu
Mascarpone, espresso-soaked savoiardi, cocoa. Chill 4 hours.
/italian> cd ../japanese
/japanese> pwd
/japanese
/japanese> exit
```

`..` steps back along the path you typed, `help` lists the commands, and
`exit`/`quit` (or Ctrl-D) leaves. The same loop reads from a pipe for
batch scripts — `#` lines are comments, a failing line reports its error
and the script continues, and the exit code tells you whether every line
succeeded:

```console
$ odag-fs < commands.txt
```

### Data tools for free (fsspec)

`OntoDAGFileSystem` is a standard fsspec filesystem, so data tools can read
straight from a concept query:

```python
import pandas as pd
from ontodag_fs import OntoDAGFileSystem, OntoDAGIndex
# ... build index/swarm as in file_it.py ...
fs = OntoDAGFileSystem(index=index, swarm=swarm)
with fs.open("/measurements/2026/data.csv") as f:
    df = pd.read_csv(f)
```

---

## 5. Things that might surprise you (by design)

- **Directories appear only where they help.** A category shows up as a
  subdirectory only if it actually *narrows* what you're looking at. You
  saw this in the tutorial: `recipe/` was absent at the root because
  everything you filed is a recipe — offering it would change nothing.
  File one non-recipe and it appears. Listings are a *live view* of your
  collection, not a fixed tree. (Typed paths always work regardless:
  `cat /recipe/caprese.md` succeeds even while `recipe/` isn't listed.)
- **No dead ends.** If a category would be hidden as unhelpful, whatever is
  under it is listed directly instead (the *coverage rule*): everything
  below your current query is always either a file right there or inside a
  visible subdirectory. A file's display position can shift deeper as your
  collection grows; every old path keeps working.
- **A file "moves" when its meaning does — never its bytes.** All
  reclassification (v0.1: `cp`, `rm`, `mv` between concept dirs) edits
  categories only. `rm` retracts a classification; it cannot destroy
  content (Swarm is immutable — the guide-rail is honest).
- **`du` overcounts; naive recursive copy duplicates.** The same object
  legitimately appears under many paths. This is a semantic view, not a
  backup target — for backups, use `.all/` at the root, which lists each
  object exactly once.
- **v0 is read-only through the mount.** `cp`/`rm`/`mv`/`mkdir` raise a
  clear error today. Creating categories always goes through `odag`.

---

## 6. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `no usable postage stamp` / `PermissionError` on filing | No valid stamp on your node. Buy one; set `BEE_BATCH`. Reads never need a stamp. |
| `Connection refused` to `localhost:1633` | Bee isn't running (or is elsewhere — set `BEE_API`). |
| `odag-fs mount` says it needs fusepy | `pip install fusepy` (plus the OS `libfuse` package, e.g. `apt install fuse3`). |
| `tree /` shows only `.all/`, `.swarm/`, `.unfiled/` | The store has categories but no *filed objects* — directories appear when there is something to refine. File something (§3 step 2). |
| `not found` for a path you expect | Category name typo (unknown categories are `ENOENT`), or the file's label collides in that listing — check for the `name~hash` form with `ls`. |
| Filed something, old listing shows | Listings cache briefly (30 s TTL) for out-of-band edits; your own writes through one process invalidate instantly. |

---

## 7. Glossary

| Term | Meaning |
|---|---|
| **category / attribute** | a named tag; may have parent categories (subsumption) |
| **ontology / DAG** | your categories and their parent links (OntoDAG) |
| **classification / intent** | the set of categories a file has, including implied parents |
| **extent** | all files at or below a query — what `.all/` lists |
| **concept** | a query result treated as a place: intent + extent |
| **object** | one stored file: Swarm reference (identity) + classification + label |
| **Swarm reference** | 64-hex content address of the bytes; also the checksum |
| **postage stamp** | prepaid Swarm storage; needed for writes only |
| **store** | a named, versioned home for one ontology (`swarm:NAME` via recordstore) |

*(For readers who know Formal Concept Analysis: intent/extent/closure here
are the subsumption-based versions, not FCA's extensional operators — see
DESIGN_DECISIONS #19 for exactly how and why they differ.)*

---

## 8. What's coming

- **v0.1 — filing through the filesystem**: `cp file ~/mnt/dessert/` stores
  and classifies in one step; `rm` retracts; `mv` reclassifies; filing
  existing Swarm content by reference (`/.swarm/<ref>` → concept dir)
  without re-uploading.
- **v1 — workflow tools**: `odag-fs import <folder>` (turn a directory
  tree into classifications, with provenance tags for later cleanup), label
  renaming, `/.unfiled/` management, and classification visible as extended
  attributes (`getfattr`).

See [ROADMAP.md](../ROADMAP.md) for the full picture.
