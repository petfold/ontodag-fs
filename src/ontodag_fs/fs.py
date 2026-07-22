"""OntoDAGFileSystem — fsspec view of an OntoDAG concept lattice.

Stateless glue (CLAUDE.md): concepts and object→intent mappings come from a
ConceptIndex (OntoDAG); bytes come from a swarmfs SwarmFileSystem. Paths are
unordered attribute sets resolved by FCA closure; directories are concepts;
files are classified objects named by display label (identity is the Swarm
reference).

v0 surface: read-only. All write methods raise NotImplementedError.
"""

from __future__ import annotations

import posixpath
import re
import time
from collections import OrderedDict
from typing import Iterable, Sequence

from fsspec import AbstractFileSystem
from fsspec.asyn import sync
from fsspec.spec import AbstractBufferedFile

from .index import ConceptIndex, ObjectInfo, UnknownAttributeError

_SWARM_REF_RE = re.compile(r"^[0-9a-f]{64}(?:[0-9a-f]{64})?$", re.IGNORECASE)
# label~shorthash disambiguation: 8+ hex chars after the final '~' of the stem
_SUFFIX_RE = re.compile(r"^(?P<label>.*)~(?P<hash>[0-9a-fA-F]{8,})$", re.DOTALL)

_V01 = "ontodag-fs v0 is read-only; filing (writes) lands in v0.1"
_DEFERRED = (
    "lattice editing through the mount is deferred — concept creation/removal "
    "goes through OntoDAG's own API (see DESIGN_DECISIONS.md)"
)


# --------------------------------------------------------------------- naming


def disambiguate(objects: Sequence[ObjectInfo]) -> dict[str, ObjectInfo]:
    """SPEC §2 naming policy: unique labels shown as-is; colliding labels
    shown as `{stem}~{shorthash}{ext}`. Deterministic per listing. If the
    8-char shorthashes themselves collide, the hash is extended until the
    names differ."""
    by_label: dict[str, list[ObjectInfo]] = {}
    for o in objects:
        by_label.setdefault(o.label, []).append(o)
    out: dict[str, ObjectInfo] = {}
    for label, group in by_label.items():
        if len(group) == 1:
            out[label] = group[0]
            continue
        stem, ext = posixpath.splitext(label)
        n = 8
        while len({o.ref[:n] for o in group}) < len(group) and n < 128:
            n += 8
        for o in group:
            out[f"{stem}~{o.ref[:n]}{ext}"] = o
    return out


def match_object(objects: Sequence[ObjectInfo], basename: str) -> ObjectInfo | None:
    """Resolve a shown name back to an object: exact label when unique,
    `label~shorthash` form always (SPEC §2)."""
    exact = [o for o in objects if o.label == basename]
    if len(exact) == 1:
        return exact[0]
    stem, ext = posixpath.splitext(basename)
    m = _SUFFIX_RE.match(stem)
    if m:
        label = m.group("label") + ext
        prefix = m.group("hash").lower()
        hits = [o for o in objects if o.label == label and o.ref.lower().startswith(prefix)]
        if len(hits) == 1:
            return hits[0]
    return None


# --------------------------------------------------------------------- cache


class _TTLCache:
    """LRU + TTL + generation-checked cache (SPEC §4)."""

    def __init__(self, maxsize: int, ttl: float) -> None:
        self.maxsize = maxsize
        self.ttl = ttl
        self._data: OrderedDict = OrderedDict()

    def get(self, key, generation):
        hit = self._data.get(key)
        if hit is None:
            return None
        value, expires, gen = hit
        if gen != generation or time.monotonic() > expires:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return value

    def put(self, key, generation, value) -> None:
        self._data[key] = (value, time.monotonic() + self.ttl, generation)
        self._data.move_to_end(key)
        while len(self._data) > self.maxsize:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()


# ----------------------------------------------------------------------- file


class _RawSwarmFile(AbstractBufferedFile):
    """Read-only file over a raw Swarm reference, range-fetching lazily."""

    def __init__(self, fs, path, ref, size, **kwargs):
        self.ref = ref
        super().__init__(fs, path, mode="rb", size=size, **kwargs)

    def _fetch_range(self, start, end):
        return self.fs._swarm_cat(self.ref, start, end)


# ------------------------------------------------------------------------ fs


class OntoDAGFileSystem(AbstractFileSystem):
    """fsspec AbstractFileSystem over (ConceptIndex, SwarmFileSystem).

    Namespace (SPEC §2):
      /<attrs...>/          concept (unordered attribute-set query)
      /<attrs...>/.all/     full extent of the concept, flattened
      /.swarm/<ref>         raw read-through to Swarm by content address
      /.swarm/<ref>/<sub>   manifest read-through, delegated to swarmfs
      /.unfiled/            objects with empty/retracted intent

    `ls("/.swarm")` returns [] — Swarm content is not enumerable.
    A name can denote both an attribute and an object label in the same
    concept: the attribute wins for isdir/info/ls, the object wins for
    isfile/cat/open (SPEC §3).
    """

    protocol = "ontodag"
    root_marker = "/"
    cachable = False  # instances carry live index/swarm handles

    def __init__(
        self,
        index: ConceptIndex,
        swarm,
        listing_ttl: float = 30.0,
        listing_cache_size: int = 1024,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.index = index
        self.swarm = swarm
        self._concepts = _TTLCache(listing_cache_size, listing_ttl)
        self._extents = _TTLCache(listing_cache_size, listing_ttl)
        self._sizes: dict[str, int] = {}  # ref -> size; content-addressed, immutable

    # ------------------------------------------------------------- plumbing

    def _parts(self, path) -> list[str]:
        path = self._strip_protocol(path)
        return [p for p in path.split("/") if p]

    def _generation(self) -> int:
        gen = getattr(self.index, "generation", None)
        return gen() if callable(gen) else 0

    def _closure(self, attrs: Iterable[str], path: str) -> frozenset[str]:
        attrs = list(attrs)
        if any(a.startswith(".") for a in attrs):
            raise FileNotFoundError(path)  # reserved namespace, never an attribute
        try:
            return self.index.closure(attrs)
        except UnknownAttributeError:
            raise FileNotFoundError(path) from None

    def _concept_listing(self, intent: frozenset[str]):
        gen = self._generation()
        cached = self._concepts.get(intent, gen)
        if cached is None:
            children = tuple(sorted(self.index.children(intent)))
            named = disambiguate(self.index.objects_at(intent))
            cached = (children, named)
            self._concepts.put(intent, gen, cached)
        return cached

    def _extent_listing(self, intent: frozenset[str]) -> dict[str, ObjectInfo]:
        gen = self._generation()
        cached = self._extents.get(intent, gen)
        if cached is None:
            cached = disambiguate(self.index.extent(intent))
            self._extents.put(intent, gen, cached)
        return cached

    # raw byte access; see also the note in _swarm_cat about the private API
    def _swarm_cat(self, ref: str, start=None, end=None) -> bytes:
        # swarmfs exposes raw-reference reads only internally today
        # (_read_reference goes through its verifying reader); ontodag-fs
        # needs exactly that primitive, so use it until swarmfs grows a
        # public one.
        return sync(self.swarm.loop, self.swarm._read_reference, ref, start, end)

    def _swarm_size(self, ref: str) -> int:
        size = self._sizes.get(ref)
        if size is None:

            async def _sz():
                reader = await self.swarm._get_reader()
                return await reader.bytes_size(ref)

            size = sync(self.swarm.loop, _sz)
            if len(self._sizes) > 65536:
                self._sizes.clear()
            self._sizes[ref] = size
        return size

    # ----------------------------------------------------------- resolution

    def _lookup_file(self, parts: list[str], path: str) -> ObjectInfo:
        """Resolve path components to an object, or raise FileNotFoundError.

        Basename matches against the object-concept members first (what plain
        `ls` shows), then against the full extent — listing is scoped but
        reachability is universal (SPEC §2)."""
        if not parts:
            raise FileNotFoundError(path)
        *dir_parts, base = parts
        if base in (".all", ".swarm", ".unfiled") or not base:
            raise FileNotFoundError(path)

        if dir_parts and dir_parts[0] == ".unfiled":
            if len(dir_parts) != 1:
                raise FileNotFoundError(path)
            obj = match_object(self.index.unfiled(), base)
            if obj is None:
                raise FileNotFoundError(path)
            return obj

        in_all = bool(dir_parts) and dir_parts[-1] == ".all"
        if in_all:
            dir_parts = dir_parts[:-1]
        intent = self._closure(dir_parts, path)

        if in_all:
            candidates = self._extent_listing(intent)
        else:
            _, candidates = self._concept_listing(intent)
        obj = match_object(list(candidates.values()), base)
        if obj is None and not in_all:
            obj = match_object(list(self._extent_listing(intent).values()), base)
        if obj is None:
            raise FileNotFoundError(path)
        return obj

    # ------------------------------------------------------------- entries

    @staticmethod
    def _join(parts: Sequence[str]) -> str:
        return "/" + "/".join(parts) if parts else "/"

    def _dir_entry(self, path: str) -> dict:
        return {"name": path, "size": 0, "type": "directory"}

    def _file_entry(self, path: str, obj: ObjectInfo, size=None) -> dict:
        return {
            "name": path,
            "size": size,
            "type": "file",
            "swarm_ref": obj.ref,
            "label": obj.label,
            "intent": sorted(obj.intent),
        }

    # ------------------------------------------------------------------- ls

    def ls(self, path, detail=False, **kwargs):
        parts = self._parts(path)

        if parts and parts[0] == ".swarm":
            entries = self._ls_swarm(parts)
        elif parts and parts[0] == ".unfiled":
            entries = self._ls_unfiled(parts)
        else:
            entries = self._ls_concept(parts)

        entries = sorted(entries, key=lambda e: e["name"])
        if detail:
            return entries
        return [e["name"] for e in entries]

    def _ls_swarm(self, parts: list[str]) -> list[dict]:
        if len(parts) == 1:
            return []  # Swarm is content-addressed: not enumerable
        ref, sub = parts[1], parts[2:]
        if not _SWARM_REF_RE.match(ref):
            raise FileNotFoundError(self._join(parts))
        if not sub:
            # a bare reference is a raw file (SPEC: raw read-through)
            return [self._swarm_raw_entry(ref)]
        inner = self.swarm.ls("/".join(parts[1:]), detail=True)
        return [{**e, "name": "/.swarm/" + e["name"].lstrip("/")} for e in inner]

    def _swarm_raw_entry(self, ref: str) -> dict:
        try:
            size = self._swarm_size(ref)
        except (OSError, ValueError):
            raise FileNotFoundError(f"/.swarm/{ref}") from None
        return {"name": f"/.swarm/{ref}", "size": size, "type": "file", "swarm_ref": ref}

    def _ls_unfiled(self, parts: list[str]) -> list[dict]:
        if len(parts) == 1:
            named = disambiguate(self.index.unfiled())
            return [self._file_entry(f"/.unfiled/{n}", o) for n, o in named.items()]
        obj = self._lookup_file(parts, self._join(parts))
        return [self._file_entry(self._join(parts), obj)]

    def _ls_concept(self, parts: list[str]) -> list[dict]:
        path = self._join(parts)
        want_all = bool(parts) and parts[-1] == ".all"
        attrs = parts[:-1] if want_all else parts

        try:
            intent = self._closure(attrs, path)
        except FileNotFoundError:
            if want_all:
                raise
            obj = self._lookup_file(parts, path)  # ls of a file → its entry
            return [self._file_entry(path, obj)]

        base = "" if path == "/" else path
        if want_all:
            named = self._extent_listing(intent)
            return [self._file_entry(f"{base}/{n}", o) for n, o in named.items()]

        children, named = self._concept_listing(intent)
        entries = [self._dir_entry(f"{base}/{c}") for c in children]
        entries.append(self._dir_entry(f"{base}/.all"))
        if not parts:
            entries.append(self._dir_entry("/.swarm"))
            entries.append(self._dir_entry("/.unfiled"))
        entries.extend(self._file_entry(f"{base}/{n}", o) for n, o in named.items())
        return entries

    # ----------------------------------------------------------------- info

    def info(self, path, **kwargs):
        parts = self._parts(path)
        norm = self._join(parts)

        if parts and parts[0] == ".swarm":
            if len(parts) == 1:
                return self._dir_entry("/.swarm")
            if len(parts) == 2:
                return self._swarm_raw_entry(parts[1])
            inner = self.swarm.info("/".join(parts[1:]))
            return {**inner, "name": "/.swarm/" + inner["name"].lstrip("/")}

        if parts and parts[0] == ".unfiled":
            if len(parts) == 1:
                return self._dir_entry("/.unfiled")
            obj = self._lookup_file(parts, norm)
            return self._file_entry(norm, obj, size=self._swarm_size(obj.ref))

        want_all = bool(parts) and parts[-1] == ".all"
        attrs = parts[:-1] if want_all else parts
        try:
            intent = self._closure(attrs, norm)
            entry = self._dir_entry(norm)
            entry["intent"] = sorted(intent)
            return entry
        except FileNotFoundError:
            obj = self._lookup_file(parts, norm)
            return self._file_entry(norm, obj, size=self._swarm_size(obj.ref))

    # ------------------------------------------------------------ existence

    def exists(self, path, **kwargs):
        try:
            self.info(path)
            return True
        except FileNotFoundError:
            return False

    def isdir(self, path):
        parts = self._parts(path)
        if not parts:
            return True
        if parts[0] == ".swarm":
            if len(parts) <= 2:  # /.swarm itself; a bare ref is a file
                return len(parts) == 1
            try:
                return self.swarm.isdir("/".join(parts[1:]))
            except OSError:
                return False
        if parts[0] == ".unfiled":
            return len(parts) == 1
        attrs = parts[:-1] if parts[-1] == ".all" else parts
        try:
            self._closure(attrs, self._join(parts))
            return True
        except FileNotFoundError:
            return False

    def isfile(self, path):
        parts = self._parts(path)
        if not parts:
            return False
        if parts[0] == ".swarm":
            if len(parts) == 1:
                return False
            if len(parts) == 2:
                try:
                    self._swarm_raw_entry(parts[1])
                    return True
                except FileNotFoundError:
                    return False
            try:
                return self.swarm.isfile("/".join(parts[1:]))
            except OSError:
                return False
        try:
            self._lookup_file(parts, self._join(parts))
            return True
        except FileNotFoundError:
            return False

    # ----------------------------------------------------------------- read

    def _resolve_ref(self, path) -> str:
        """Path → Swarm reference of the object it denotes (files only)."""
        parts = self._parts(path)
        norm = self._join(parts)
        if parts and parts[0] == ".swarm" and len(parts) == 2:
            ref = parts[1]
            if not _SWARM_REF_RE.match(ref):
                raise FileNotFoundError(norm)
            return ref.lower()
        if self.isdir(norm) and not self.isfile(norm):
            raise IsADirectoryError(norm)
        return self._lookup_file(parts, norm).ref

    def cat_file(self, path, start=None, end=None, **kwargs):
        parts = self._parts(path)
        if parts and parts[0] == ".swarm" and len(parts) > 2:
            return self.swarm.cat_file("/".join(parts[1:]), start=start, end=end)
        return self._swarm_cat(self._resolve_ref(path), start, end)

    def _open(
        self,
        path,
        mode="rb",
        block_size=None,
        autocommit=True,
        cache_options=None,
        **kwargs,
    ):
        if mode != "rb":
            raise NotImplementedError(f"open(mode={mode!r}): {_V01}")
        parts = self._parts(path)
        if parts and parts[0] == ".swarm" and len(parts) > 2:
            return self.swarm.open("/".join(parts[1:]), mode="rb")
        ref = self._resolve_ref(path)
        return _RawSwarmFile(
            self,
            self._join(parts),
            ref,
            size=self._swarm_size(ref),
            block_size=block_size,
            cache_options=cache_options,
        )

    def checksum(self, path):
        """The Swarm reference: the content address IS the checksum."""
        return self._resolve_ref(path)

    # ---------------------------------------------------------------- cache

    def invalidate_cache(self, path=None):
        self._concepts.clear()
        self._extents.clear()

    # ------------------------------------------------------------ write ops
    # v0 is read-only for objects; the lattice is read-only through the
    # mount in every version so far (SPEC §3, DESIGN_DECISIONS.md #8).

    def mkdir(self, path, create_parents=True, **kwargs):
        raise NotImplementedError(f"mkdir: {_DEFERRED}")

    def makedirs(self, path, exist_ok=False):
        raise NotImplementedError(f"makedirs: {_DEFERRED}")

    def rmdir(self, path):
        raise NotImplementedError(f"rmdir: {_DEFERRED}")

    def pipe_file(self, path, value, **kwargs):
        raise NotImplementedError(f"pipe_file: {_V01}")

    def put_file(self, lpath, rpath, **kwargs):
        raise NotImplementedError(f"put_file: {_V01}")

    def rm(self, path, recursive=False, maxdepth=None):
        raise NotImplementedError(f"rm: {_V01}")

    def rm_file(self, path):
        raise NotImplementedError(f"rm: {_V01}")

    def mv(self, path1, path2, **kwargs):
        raise NotImplementedError(f"mv: {_V01}")

    def cp_file(self, path1, path2, **kwargs):
        raise NotImplementedError(f"cp: {_V01}")

    def touch(self, path, truncate=True, **kwargs):
        raise NotImplementedError(
            "touch: rejected — every empty file has the same content address "
            "(SPEC §3, explicitly rejected mappings)"
        )
