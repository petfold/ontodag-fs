"""Thin browse CLI for the v0 manual milestone (the full CLI is ROADMAP v1).

Loads a DAG through odag's store machinery — the same store specs odag
uses: a path to a native/OWL file, or ``swarm:NAME`` — and serves it
read-only with OntoDAGFileSystem over swarmfs.

    odag-fs [-s STORE] [--bee-api URL] COMMAND ...

Commands: ls, tree, cat, info, mount, set. ``set`` reads and writes the
same ``~/.ontodag/config`` as odag (keys: store, bee_api, bee_batch), so
``odag set store swarm:NAME`` and ``odag-fs set store swarm:NAME`` are
interchangeable and every command needs no ``-s`` once a default store is
set. With nothing configured the default is the local ``~/.ontodag``
store. ``mount`` uses fsspec's generic FUSE wrapper (needs fusepy;
deployment mode, not architecture).
"""

from __future__ import annotations

import argparse
import os
import sys


def _build_fs(store_spec: str | None, bee_api: str | None):
    # odag's CLI module is the authority on store specs/config; reusing its
    # (private) helpers is accepted milestone tooling — the real CLI (v1)
    # gets a public seam.
    from ontodag.__main__ import _make_backend, _read_config, _resolve_store

    from swarmfs import SwarmFileSystem

    from . import OntoDAGFileSystem, OntoDAGIndex

    dag = _make_backend(_resolve_store(store_spec)).load()
    api = bee_api or os.environ.get("BEE_API") or _read_config().get("bee_api")
    swarm = SwarmFileSystem(api_url=api) if api else SwarmFileSystem()
    return OntoDAGFileSystem(index=OntoDAGIndex(dag), swarm=swarm)


def _basename(entry: dict) -> str:
    return entry["name"].rstrip("/").rsplit("/", 1)[-1]


def cmd_ls(fs, args) -> None:
    for e in fs.ls(args.path, detail=True):
        base = _basename(e)
        if e["type"] == "directory":
            print(base + "/")
        elif args.long:
            print(f"{base}  [{e.get('swarm_ref', '')[:8]}]  {sorted(e.get('intent', []))}")
        else:
            print(base)


def cmd_tree(fs, args) -> None:
    print(args.path if args.path.startswith("/") else "/" + args.path)
    _tree(fs, args.path, args.depth)


def _tree(fs, path, depth, prefix="") -> None:
    entries = fs.ls(path, detail=True)
    entries.sort(key=lambda e: (e["type"] != "directory", e["name"]))
    for i, e in enumerate(entries):
        last = i == len(entries) - 1
        connector = "└── " if last else "├── "
        base = _basename(e)
        if e["type"] == "directory":
            print(prefix + connector + base + "/")
            # .swarm is unenumerable; .all repeats what the tree already
            # shows — descend the lattice and .unfiled only
            if depth > 1 and base not in (".all", ".swarm"):
                _tree(fs, e["name"], depth - 1, prefix + ("    " if last else "│   "))
        else:
            ref = e.get("swarm_ref", "")
            print(prefix + connector + base + (f"  [{ref[:8]}]" if ref else ""))


def cmd_cat(fs, args) -> None:
    sys.stdout.buffer.write(fs.cat_file(args.path))


def cmd_info(fs, args) -> None:
    for key, value in fs.info(args.path).items():
        print(f"{key}: {value}")


def cmd_mount(fs, args) -> None:
    try:
        from fsspec.fuse import run
    except ImportError:
        sys.exit("odag-fs mount needs fusepy: pip install fusepy")
    print(f"mounting ontodag view at {args.mountpoint} — Ctrl-C or "
          f"`fusermount -u {args.mountpoint}` to unmount")
    run(fs, "/", args.mountpoint)


def cmd_set(args) -> None:
    """Show or change settings — same keys and config file as odag's `set`
    (~/.ontodag/config), so either tool's `set store` configures both."""
    from ontodag.__main__ import (
        _SETTINGS,
        _normalize_spec,
        _read_config,
        _resolve_store,
        _write_config,
    )

    def effective(key: str) -> str:
        cfg = _read_config()
        if key == "store":
            return _resolve_store(None)
        if key == "bee_api":
            return os.environ.get("BEE_API") or cfg.get("bee_api") or "http://localhost:1633"
        if key == "bee_batch":
            return os.environ.get("BEE_BATCH") or cfg.get("bee_batch") or ""
        return cfg.get(key, "")

    if not args.key:
        for key in _SETTINGS:
            print(f"{key} = {effective(key)}")
        return
    if args.key not in _SETTINGS:
        sys.exit(f"odag-fs: unknown setting: {args.key} "
                 f"(known: {', '.join(_SETTINGS)})")
    if args.value is None:
        print(f"{args.key} = {effective(args.key)}")
        return
    cfg = _read_config()
    cfg[args.key] = _normalize_spec(args.value) if args.key == "store" else args.value
    _write_config(cfg)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="odag-fs",
        description="Browse an OntoDAG concept lattice as a filesystem "
                    "(read-only, v0). Settings are shared with odag: "
                    "`odag-fs set store swarm:NAME` makes -s unnecessary.",
    )
    parser.add_argument("-s", "--store", default=None,
                        help="one-off store override: a file path or "
                             "swarm:NAME (default: the configured store; "
                             "see `odag-fs set`)")
    parser.add_argument("--bee-api", default=None,
                        help="Bee API URL for the bytestore (default: "
                             "$BEE_API, configured bee_api, or localhost)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ls", help="list a concept directory")
    p.add_argument("path", nargs="?", default="/")
    p.add_argument("-l", "--long", action="store_true")
    p.set_defaults(func=cmd_ls)

    p = sub.add_parser("tree", help="recursive listing of the lattice")
    p.add_argument("path", nargs="?", default="/")
    p.add_argument("--depth", type=int, default=4)
    p.set_defaults(func=cmd_tree)

    p = sub.add_parser("cat", help="print an object's bytes")
    p.add_argument("path")
    p.set_defaults(func=cmd_cat)

    p = sub.add_parser("info", help="show info for a path")
    p.add_argument("path")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("mount", help="FUSE-mount the view (needs fusepy)")
    p.add_argument("mountpoint")
    p.set_defaults(func=cmd_mount)

    p = sub.add_parser("set", help="show or change settings (shared with odag)")
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")

    args = parser.parse_args(argv)
    if args.command == "set":
        cmd_set(args)
        return
    fs = _build_fs(args.store, args.bee_api)
    try:
        args.func(fs, args)
    except FileNotFoundError as exc:
        sys.exit(f"odag-fs: not found: {exc}")
    except IsADirectoryError as exc:
        sys.exit(f"odag-fs: is a directory: {exc}")


if __name__ == "__main__":
    main()
