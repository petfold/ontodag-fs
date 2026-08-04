"""docs/REFERENCE.md is pinned to the code: if a name, a parameter, or the
export list in that file and the package disagree, this suite fails.
(Same pattern as ontodag, recordstore and swarmfs.)"""

import inspect
import re
from pathlib import Path

import ontodag_fs

DOC = Path(__file__).parent.parent / "docs" / "REFERENCE.md"
TEXT = DOC.read_text(encoding="utf-8")


def _table_rows(section: str) -> list[list[str]]:
    m = re.search(rf"^## {re.escape(section)}.*?(?=^## |\Z)", TEXT,
                  re.M | re.S)
    assert m, f"section {section!r} missing from REFERENCE.md"
    rows = []
    for line in m.group(0).splitlines():
        if line.startswith("|") and not re.match(r"^\|[\s\-|]+\|$", line):
            rows.append([c.strip() for c in line.strip("|").split("|")])
    return rows[1:] if rows else []


def _first_code(cell: str) -> str | None:
    m = re.match(r"`([^`]+)`", cell)
    return m.group(1) if m else None


def _resolve(dotted: str):
    obj = ontodag_fs
    for part in dotted.split("."):
        obj = getattr(obj, part)
    return obj


def test_exports_table_is_exactly_dunder_all():
    documented = {
        _first_code(row[0])
        for row in _table_rows("3. Exports")
        if _first_code(row[0])
    }
    assert documented == set(ontodag_fs.__all__), (
        f"only in docs: {documented - set(ontodag_fs.__all__)}; "
        f"only in __all__: {set(ontodag_fs.__all__) - documented}")


def test_documented_names_resolve():
    checked = 0
    for section in ["4. `OntoDAGFileSystem`", "6. `ConceptIndex` (the protocol)"]:
        for row in _table_rows(section):
            name = _first_code(row[0])
            if not (name and re.fullmatch(r"[A-Za-z_][\w.]*", name)):
                continue
            try:
                _resolve(name)
            except AttributeError as e:
                raise AssertionError(
                    f"{section}: `{name}` does not resolve: {e}") from None
            checked += 1
    assert checked >= 9


def test_constructor_parameters_exist():
    row = next(r for r in _table_rows("4. `OntoDAGFileSystem`")
               if _first_code(r[0]) == "OntoDAGFileSystem")
    real = set(inspect.signature(
        ontodag_fs.OntoDAGFileSystem.__init__).parameters) | {"self"}
    for chunk in _first_code(row[1]).strip("()").split(","):
        param = re.split(r"[=:]", chunk.strip())[0].strip("* ")
        if re.fullmatch(r"[A-Za-z_]\w*", param):
            assert param in real, (
                f"documented parameter {param!r} not on OntoDAGFileSystem "
                f"(real: {sorted(real)})")


def test_object_info_fields_documented():
    for field in ontodag_fs.ObjectInfo.__dataclass_fields__:
        assert f"`{field}`" in TEXT, (
            f"ObjectInfo field {field!r} missing from REFERENCE.md")


def test_described_version_matches_pyproject():
    doc_version = re.search(
        r"version this file describes: `([\d.]+)`", TEXT).group(1)
    pyproject = (Path(__file__).parent.parent / "pyproject.toml").read_text()
    real = re.search(r'^version = "([\d.]+)"', pyproject, re.M).group(1)
    assert doc_version == real, (
        f"REFERENCE.md describes {doc_version}, pyproject says {real} — "
        "update the reference as part of the release docs sweep")
