"""ontodag-fs: an OntoDAG concept lattice as an fsspec filesystem over Swarm."""

from .fs import OntoDAGFileSystem
from .index import ConceptIndex, ObjectInfo, UnknownAttributeError
from .memory import InMemoryIndex

__all__ = [
    "ConceptIndex",
    "InMemoryIndex",
    "ObjectInfo",
    "OntoDAGFileSystem",
    "UnknownAttributeError",
]
