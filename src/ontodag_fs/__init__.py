"""ontodag-fs: an OntoDAG concept lattice as an fsspec filesystem over Swarm."""

from .fs import OntoDAGFileSystem
from .index import ConceptIndex, ObjectInfo, UnknownAttributeError
from .memory import InMemoryIndex
from .ontodag_index import OntoDAGIndex

__all__ = [
    "ConceptIndex",
    "InMemoryIndex",
    "ObjectInfo",
    "OntoDAGFileSystem",
    "OntoDAGIndex",
    "UnknownAttributeError",
]
