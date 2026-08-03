"""Path-component encoding: DAG names ↔ POSIX path components.

A DAG name is an arbitrary string. A POSIX path component is not: it cannot
contain ``/`` (the separator) or NUL. Until ontodag 0.10.0 the gap was
theoretical — asserted attribute names are validated path-clean
(:func:`ontodag_fs.memory.validate_attribute`) and every canonical value name
was integers-in-base-units (``weight(3000000mg)``). Registry 3.0 made canonical
values *reduced rationals* of the SI anchor, so ``weight(4.5kg)`` now
canonicalizes to ``weight(9/2kg)``: an ordinary name that no directory entry
can carry. Object labels have always been able to hold a ``/`` — they are
display metadata, never validated (hard rule 1).

So the fix is one reversible mapping applied at the path boundary, not a
restriction on names:

    encode:  '%' → '%25',  '/' → '%2F',  NUL → '%00'
    decode:  those three triplets, in a single left-to-right pass

**Law:** ``decode(encode(s)) == s`` for every string ``s`` — the same shape as
ontodag's own surface law ``elaborate(render(t)) == t``. Every name containing
no ``%``, ``/`` or NUL is returned byte-identical, so no path that resolved
before this layer existed resolves differently now.

Decoding is deliberately *strict* — only those three triplets are recognised,
not general percent-decoding. That buys backward compatibility: a raw DAG name
typed straight into a path (``/100%``) still resolves, because a bare ``%`` is
left alone. The cost is a knowingly accepted ambiguity: the encoded form of
``weight(%2Fkg)`` is ``weight(%252Fkg)``, so a user typing the raw name
``weight(%2Fkg)`` addresses ``weight(/kg)`` instead. The law above is what the
filesystem relies on; the ambiguity only affects names that already contain a
percent triplet, and it resolves in favour of the encoded reading.

Scope: entry ``name`` fields are encoded, because they are paths. The ``label``
and ``intent`` fields of a listing are *data* — raw DAG names and raw display
labels — and are never encoded. The ``/.swarm/`` subtree is a read-through to
swarmfs's own namespace, not the DAG's, and is passed through untouched.
"""

from __future__ import annotations

import re

# Order matters on the way out: '%' first, or the escapes get double-encoded.
_ENCODE = (("%", "%25"), ("/", "%2F"), ("\x00", "%00"))
_DECODE_RE = re.compile("%(25|2[Ff]|00)")


def encode_component(name: str) -> str:
    """A DAG name (or display label) as a single POSIX path component."""
    for raw, escaped in _ENCODE:
        name = name.replace(raw, escaped)
    return name


def decode_component(component: str) -> str:
    """A path component back to the DAG name it denotes."""
    return _DECODE_RE.sub(lambda m: chr(int(m.group(1), 16)), component)
