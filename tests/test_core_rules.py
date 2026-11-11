"""Regeln des schnellen Testkerns zur Datenebene (docs/grundgeruest.md, Abschnitt 9)."""

import ast
import importlib
import pkgutil
from pathlib import Path

import moarcoal
from moarcoal.storage import all_kinds, kind_collisions

SRC = Path(__file__).parent.parent / "src" / "moarcoal"
STORAGE_PACKAGE = "storage"

FILE_METHODS = {
    "open",
    "read_text",
    "read_bytes",
    "write_text",
    "write_bytes",
    "unlink",
    "mkdir",
    "rmdir",
    "touch",
    "rename",
    "iterdir",
    "glob",
    "rglob",
}
FILE_MODULES = {"shutil", "tempfile", "glob", "fileinput"}
OS_FILE_FUNCTIONS = {"open", "remove", "rename", "replace", "unlink", "mkdir", "makedirs", "fsync"}


def import_all_modules() -> None:
    for module in pkgutil.walk_packages(moarcoal.__path__, "moarcoal."):
        importlib.import_module(module.name)


def direct_file_access(source: str) -> list[str]:
    """Stellen im Quelltext, die Dateien an der Datenebene vorbei lesen oder schreiben."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import | ast.ImportFrom):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            found += [f"import {n}" for n in names if n.split(".")[0] in FILE_MODULES]
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "open":
                found.append("open(...)")
            elif isinstance(func, ast.Attribute):
                owner = func.value
                if func.attr in FILE_METHODS:
                    found.append(f".{func.attr}(...)")
                elif (
                    isinstance(owner, ast.Name)
                    and owner.id == "os"
                    and func.attr in OS_FILE_FUNCTIONS
                ):
                    found.append(f"os.{func.attr}(...)")
    return found


def test_kinds_are_unique_across_all_modules() -> None:
    import_all_modules()
    assert kind_collisions(all_kinds()) == []


def test_nothing_outside_the_storage_package_touches_files() -> None:
    offenders: dict[str, list[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(SRC)
        if relative.parts[0] == STORAGE_PACKAGE:
            continue
        found = direct_file_access(path.read_text(encoding="utf-8"))
        if found:
            offenders[relative.as_posix()] = found
    assert not offenders, f"Dateizugriff außerhalb der Datenebene: {offenders}"


def test_file_access_check_finds_direct_access() -> None:
    assert direct_file_access("data = open('x').read()") == ["open(...)"]
    assert direct_file_access("Path('x').write_text('y')") == [".write_text(...)"]
    assert direct_file_access("import os\nos.replace(a, b)") == ["os.replace(...)"]
    assert direct_file_access("import shutil") == ["import shutil"]
    assert direct_file_access("x = {}.get('a')\nos.path.join('a', 'b')") == []
