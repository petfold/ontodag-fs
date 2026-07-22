"""Offline fixtures: an in-memory ConceptIndex plus a SwarmFileSystem served
by a fake client (sha256 stands in for the BMT hash — only internal
consistency matters), so the whole stack runs without a Bee node (CLAUDE.md)."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from ontodag.dag import OntoDAG
from swarmfs import SwarmFileSystem

from ontodag_fs import InMemoryIndex, OntoDAGFileSystem, OntoDAGIndex

INDEX_BACKENDS = ("memory", "ontodag")


def make_index(backend: str):
    """Both implementations expose the same builder surface; the whole
    suite runs against each to keep their semantics identical."""
    if backend == "memory":
        return InMemoryIndex()
    return OntoDAGIndex(OntoDAG())

GOOD_STAMP = {
    "batchID": "ab" * 32,
    "usable": True,
    "batchTTL": 86400,
    "utilizationRatio": 0.25,
    "label": "test-stamp",
    "immutableFlag": True,
}


class FakeSwarmClient:
    """Duck-typed SwarmClient over an in-memory {digest: bytes} store."""

    def __init__(self, store: dict[bytes, bytes]):
        self.store = store
        self.api_url = "fake://"
        self.uploads: list[int] = []  # nbytes per upload — invariant 7 spy

    async def bytes_get(self, ref: str, start=None, end=None) -> bytes:
        data = self.store.get(bytes.fromhex(ref))
        if data is None:
            raise FileNotFoundError(ref)
        if start is None and end is None:
            return data
        return data[start or 0 : end]

    async def bytes_size(self, ref: str) -> int:
        data = self.store.get(bytes.fromhex(ref))
        if data is None:
            raise FileNotFoundError(ref)
        return len(data)

    async def bytes_iter(self, ref: str, chunk_size: int = 1 << 20):
        data = await self.bytes_get(ref)
        for i in range(0, len(data), chunk_size):
            yield data[i : i + chunk_size]

    async def bytes_post(self, data, stamp: str, **kwargs) -> str:
        if not isinstance(data, bytes):
            data.seek(0)
            data = data.read()
        ref = hashlib.sha256(data).digest()
        self.store[ref] = data
        self.uploads.append(len(data))
        return ref.hex()

    async def stamps_list(self) -> list[dict]:
        return [GOOD_STAMP]

    async def health(self) -> dict:
        return {"status": "ok", "version": "fake"}

    async def close(self) -> None:
        pass


def seed(store: dict[bytes, bytes], data: bytes) -> str:
    """Put bytes straight into the fake store; return the reference hex."""
    ref = hashlib.sha256(data).digest()
    store[ref] = data
    return ref.hex()


ATTRIBUTES = {
    "animal": [],
    "mammal": ["animal"],
    "bird": ["animal"],
    "pet": ["animal"],
    "dog": ["mammal", "pet"],
    "cat": ["mammal", "pet"],
    "canary": ["bird", "pet"],
    "wolf": ["mammal"],
    "eagle": ["bird"],
    "document": [],
}

OBJECTS = {
    # key: (bytes, label, asserted attrs)
    "rex": (b"rex the dog", "rex.jpg", {"dog"}),
    "whiskers": (b"whiskers the cat", "whiskers.jpg", {"cat"}),
    "tweety": (b"tweety", "tweety.png", {"canary"}),
    "pack": (b"wolf pack", "pack.txt", {"wolf"}),
    "dognotes": (b"dog notes", "notes.txt", {"dog"}),
    "catnotes": (b"cat notes", "notes.txt", {"cat"}),
    "readme": (b"# readme", "readme.md", {"document"}),
    "soar": (b"soaring eagle", "soar.gif", {"eagle"}),
    "orphan": (b"orphan bytes", "orphan.bin", set()),  # unfiled
}


def build_zoo(backend: str = "memory") -> SimpleNamespace:
    store: dict[bytes, bytes] = {}
    index = make_index(backend)
    for name, parents in ATTRIBUTES.items():
        index.add_attribute(name, parents)
    refs: dict[str, str] = {}
    for key, (data, label, attrs) in OBJECTS.items():
        ref = seed(store, data)
        index.add_object(ref, label, attrs)
        refs[key] = ref
    client = FakeSwarmClient(store)
    swarm = SwarmFileSystem(client=client, skip_instance_cache=True)
    fs = OntoDAGFileSystem(index=index, swarm=swarm)
    return SimpleNamespace(
        fs=fs, index=index, swarm=swarm, client=client, store=store, refs=refs
    )


@pytest.fixture(params=INDEX_BACKENDS)
def zoo(request) -> SimpleNamespace:
    return build_zoo(request.param)


@pytest.fixture(params=INDEX_BACKENDS)
def zoo_tail(request) -> SimpleNamespace:
    """The v0-milestone shape: a single-object tail (rex, the only pet,
    is a dog) — the dead-end case behind decision #18."""
    store: dict[bytes, bytes] = {}
    index = make_index(request.param)
    index.add_attribute("animal")
    index.add_attribute("pet")
    index.add_attribute("dog", ["animal", "pet"])
    index.add_object(seed(store, b"rex"), "rex.txt", {"dog"})
    swarm = SwarmFileSystem(client=FakeSwarmClient(store), skip_instance_cache=True)
    fs = OntoDAGFileSystem(index=index, swarm=swarm)
    return SimpleNamespace(fs=fs, index=index, store=store)
