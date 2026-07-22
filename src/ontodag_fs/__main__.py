"""Thin browse CLI for the v0 manual milestone (the full CLI is ROADMAP v1).

Loads a DAG through odag's store machinery — the same store specs odag
uses: a path to a native/OWL file, or ``swarm:NAME`` — and serves it
read-only with OntoDAGFileSystem over swarmfs.

    odag-fs [-s STORE] [--bee-api URL] [COMMAND [args]]

Commands: ls, tree, cat, info, cd, pwd, mount, set, help. With no command,
odag-fs follows odag's convention: it reads commands from a pipe, or opens
an interactive ``>`` prompt on a terminal — with a current directory, so
paths may be relative (``cd pet`` then ``ls``). The store is hydrated once
per session, so repeated commands are fast.

``set`` reads and writes the same ``~/.ontodag/config`` as odag (keys:
store, bee_api, bee_batch), so ``odag set store swarm:NAME`` and
``odag-fs set store swarm:NAME`` are interchangeable and no ``-s`` is
needed once a default store is set. With nothing configured the default
is the local ``~/.ontodag`` store. ``mount`` uses fsspec's generic FUSE
wrapper (needs fusepy; deployment mode, not architecture).
"""

from __future__ import annotations

import argparse
import os
import posixpath
import shlex
import sys

try:
    from importlib.metadata import PackageNotFoundError, version

    try:
        __version__ = version("ontodag-fs")
    except PackageNotFoundError:
        __version__ = "dev"
except Exception:  # pragma: no cover
    __version__ = "dev"


HELP_TEXT = """\
Usage: odag-fs [-s STORE] [--bee-api URL] [<command> [args]]

Commands:
  ls [-l] [PATH]           list a concept directory
  tree [PATH] [--depth N]  recursive listing of the lattice
  cat PATH                 print an object's bytes
  info PATH                show details for a path
  cd [PATH]                change the current directory (interactive mode)
  pwd                      print the current directory
  mount MOUNTPOINT         FUSE-mount the view (needs fusepy)
  set [KEY [VALUE]]        show settings, or set one (store, bee_api, bee_batch)
  help                     show this help

With no command odag-fs reads commands from a pipe, or opens an interactive
`>` prompt on a terminal — the same convention as odag. In that mode paths
may be relative to the current directory (`cd pet` then `ls`), and the
store is loaded once for the whole session.

Settings are shared with odag (~/.ontodag/config): `set store swarm:NAME`
in either tool makes -s unnecessary everywhere. With nothing configured
the default is the local ~/.ontodag store.

Options:
  -s, --store STORE   one-off store override: a file path or swarm:NAME
  --bee-api URL       Bee API URL (default: $BEE_API, configured bee_api,
                      or localhost)
"""


# ----------------------------------------------------------------- session


class Session:
    """One loaded store + a current directory, shared across commands."""

    def __init__(self, store_spec: str | None, bee_api: str | None):
        self.store_spec = store_spec
        self.bee_api = bee_api
        self.cwd = "/"
        self._fs = None

    @property
    def fs(self):
        if self._fs is None:
            self._fs = _build_fs(self.store_spec, self.bee_api)
        return self._fs

    def switch(self) -> None:
        """Drop the loaded store (after `set store`); reload lazily."""
        self._fs = None
        self.store_spec = None  # the new config default takes over
        self.cwd = "/"

    def resolve(self, path: str) -> str:
        """Make a path absolute against the current directory (supports
        `.` and `..`, which operate on the typed path, not the lattice)."""
        if not path.startswith("/"):
            path = posixpath.join(self.cwd, path)
        norm = posixpath.normpath(path)
        return "/" if norm in (".", "//") else norm


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


# ---------------------------------------------------------------- commands


def _basename(entry: dict) -> str:
    return entry["name"].rstrip("/").rsplit("/", 1)[-1]


def cmd_ls(session: Session, args) -> None:
    for e in session.fs.ls(session.resolve(args.path), detail=True):
        base = _basename(e)
        if e["type"] == "directory":
            print(base + "/")
        elif args.long:
            print(f"{base}  [{e.get('swarm_ref', '')[:8]}]  {sorted(e.get('intent', []))}")
        else:
            print(base)


def cmd_tree(session: Session, args) -> None:
    path = session.resolve(args.path)
    print(path)
    _tree(session.fs, path, args.depth)


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


def cmd_cat(session: Session, args) -> None:
    sys.stdout.buffer.write(session.fs.cat_file(session.resolve(args.path)))
    sys.stdout.buffer.flush()


def cmd_info(session: Session, args) -> None:
    for key, value in session.fs.info(session.resolve(args.path)).items():
        print(f"{key}: {value}")


def cmd_cd(session: Session, args) -> None:
    path = session.resolve(args.path)
    if not session.fs.isdir(path):
        raise FileNotFoundError(f"not a directory: {path}")
    session.cwd = path


def cmd_pwd(session: Session, args) -> None:
    print(session.cwd)


def cmd_mount(session: Session, args) -> None:
    try:
        from fsspec.fuse import run
    except ImportError:
        raise ValueError("odag-fs mount needs fusepy: pip install fusepy") from None
    print(f"mounting ontodag view at {args.mountpoint} — Ctrl-C or "
          f"`fusermount -u {args.mountpoint}` to unmount")
    run(session.fs, "/", args.mountpoint)


def cmd_set(session: Session, args) -> None:
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
            return session.store_spec or _resolve_store(None)
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
        raise ValueError(f"unknown setting: {args.key} "
                         f"(known: {', '.join(_SETTINGS)})")
    if args.value is None:
        print(f"{args.key} = {effective(args.key)}")
        return
    cfg = _read_config()
    cfg[args.key] = _normalize_spec(args.value) if args.key == "store" else args.value
    _write_config(cfg)
    if args.key == "store":
        session.switch()


def cmd_help(session: Session, args) -> None:
    sys.stdout.write(HELP_TEXT)


# ------------------------------------------------------------------ parser


def _build_command_parser(with_globals: bool) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="odag-fs", add_help=with_globals)
    if with_globals:
        parser.add_argument("-s", "--store", default=None,
                            help="one-off store override: a file path or "
                                 "swarm:NAME (default: the configured store; "
                                 "see `odag-fs set`)")
        parser.add_argument("--bee-api", default=None,
                            help="Bee API URL for the bytestore (default: "
                                 "$BEE_API, configured bee_api, or localhost)")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser("ls", help="list a concept directory")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("-l", "--long", action="store_true")
    p.set_defaults(func=cmd_ls)

    p = sub.add_parser("tree", help="recursive listing of the lattice")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--depth", type=int, default=4)
    p.set_defaults(func=cmd_tree)

    p = sub.add_parser("cat", help="print an object's bytes")
    p.add_argument("path")
    p.set_defaults(func=cmd_cat)

    p = sub.add_parser("info", help="show info for a path")
    p.add_argument("path")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("cd", help="change the current directory")
    p.add_argument("path", nargs="?", default="/")
    p.set_defaults(func=cmd_cd)

    p = sub.add_parser("pwd", help="print the current directory")
    p.set_defaults(func=cmd_pwd)

    p = sub.add_parser("mount", help="FUSE-mount the view (needs fusepy)")
    p.add_argument("mountpoint")
    p.set_defaults(func=cmd_mount)

    p = sub.add_parser("set", help="show or change settings (shared with odag)")
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("help", help="show help")
    p.set_defaults(func=cmd_help)

    return parser


_LINE_PARSER = _build_command_parser(with_globals=False)


def dispatch(tokens: list[str], session: Session) -> int:
    """Parse one command line and run it. Returns a process-style exit code."""
    try:
        args = _LINE_PARSER.parse_args(tokens)
    except SystemExit as exc:  # argparse handled --help or a usage error
        return exc.code or 0
    if args.command is None:
        return 0
    try:
        args.func(session, args)
        return 0
    except (ValueError, OSError) as exc:
        print(f"odag-fs: {exc}", file=sys.stderr)
        return 1


# ----------------------------------------------- interactive / batch modes


def run_stream(session: Session, stream, interactive: bool) -> int:
    """Read commands line by line — `>` prompt on a tty, silently from a
    pipe. Errors are reported and the loop continues (odag convention);
    the exit code says whether every line succeeded."""
    if interactive:
        print(f"odag-fs {__version__} - type help for help")
    failed = False
    while True:
        if interactive:
            try:
                line = input(f"{session.cwd}> " if session.cwd != "/" else "> ")
            except EOFError:
                print()
                break
        else:
            line = stream.readline()
            if not line:
                break
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            tokens = shlex.split(line)
        except ValueError as exc:
            print(f"odag-fs: {exc}", file=sys.stderr)
            failed = True
            continue
        if tokens[0] in ("quit", "exit"):
            break
        if dispatch(tokens, session) != 0:
            failed = True
    return 1 if failed and not interactive else 0


# ------------------------------------------------------------- entry point


def main(argv=None) -> None:
    parser = _build_command_parser(with_globals=True)
    args = parser.parse_args(argv)
    session = Session(getattr(args, "store", None), getattr(args, "bee_api", None))

    if args.command is None:
        sys.exit(run_stream(session, sys.stdin, interactive=sys.stdin.isatty()))

    code = 0
    try:
        args.func(session, args)
    except (ValueError, OSError) as exc:
        print(f"odag-fs: {exc}", file=sys.stderr)
        code = 1
    sys.exit(code)


if __name__ == "__main__":
    main()
