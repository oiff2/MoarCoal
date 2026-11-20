"""Regeln des schnellen Testkerns zur Datenebene (docs/grundgeruest.md, Abschnitt 9)."""

import ast
import importlib
import pkgutil
import re
import warnings
from collections.abc import Collection, Iterable, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

from app_helper import make_app

import moarcoal
import moarcoal.modules
from moarcoal.modules import MODULES
from moarcoal.storage import all_kinds, kind_collisions, open_store
from moarcoal.values.catalog import ValueCatalog
from moarcoal.values.model import ValueKey

SRC = Path(__file__).parent.parent / "src" / "moarcoal"
STORAGE_PACKAGE = "storage"
# Der Claude-Aufruf legt nur sein leeres Wegwerfverzeichnis an, nie Nutzerdaten.
# Struktur und Deutschlandkarte lesen nur mitgelieferte Dateien des Repos, nie Nutzerdaten.
ALLOWED = {
    "extraction.py": {"import tempfile"},
    # `webbrowser.open` öffnet die Startseite, keine Datei; die PID-Datei liegt in `storage`.
    "__main__.py": {".open(...)"},
    "modules/tax_year/structure.py": {".read_text(...)"},
    "modules/work/trips/germany_map.py": {".read_text(...)"},
}

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
        found = [f for f in found if f not in ALLOWED.get(relative.as_posix(), set())]
        if found:
            offenders[relative.as_posix()] = found
    assert not offenders, f"Dateizugriff außerhalb der Datenebene: {offenders}"


def test_file_access_check_finds_direct_access() -> None:
    assert direct_file_access("data = open('x').read()") == ["open(...)"]
    assert direct_file_access("Path('x').write_text('y')") == [".write_text(...)"]
    assert direct_file_access("import os\nos.replace(a, b)") == ["os.replace(...)"]
    assert direct_file_access("import shutil") == ["import shutil"]
    assert direct_file_access("x = {}.get('a')\nos.path.join('a', 'b')") == []


def unknown_value_keys(
    catalog: ValueCatalog, namespaces: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    """Jeder Werte-Schlüssel, den ein Modul als Konstante nennt (eigene und fremde, die es per
    `calculation.use` anfragt) und den kein Modul im Wertekatalog angemeldet hat."""
    return [
        f"{module}.{name} = {value}"
        for module, namespace in namespaces.items()
        for name, value in namespace.items()
        if isinstance(value, ValueKey) and value not in catalog.definitions
    ]


def module_namespaces() -> dict[str, dict[str, Any]]:
    found: Iterable[ModuleType] = (
        importlib.import_module(m.name)
        for m in pkgutil.walk_packages(moarcoal.modules.__path__, "moarcoal.modules.")
    )
    return {m.__name__: vars(m) for m in found}


def test_every_value_key_a_module_names_is_in_the_catalog() -> None:
    """Fremde Schlüssel stehen als Text im Modul (Prinzip 2); ein Tippfehler fiele sonst erst zur
    Laufzeit als `UnknownValueKey` auf."""
    catalog = ValueCatalog.of((m.key, m.values) for m in MODULES)
    assert unknown_value_keys(catalog, module_namespaces()) == []


def test_value_key_check_finds_a_typo() -> None:
    catalog = ValueCatalog.of((m.key, m.values) for m in MODULES)
    namespace = {"WORK_DAYS": ValueKey("work.workday"), "OTHER": "work.workday"}
    assert unknown_value_keys(catalog, {"beispiel": namespace}) == [
        "beispiel.WORK_DAYS = work.workday"
    ]


LAYER_PACKAGES = ("storage", "values")  # die Datenebene im engen Sinn (Prinzip 1)
WEB_LIBRARIES = {"fastapi", "starlette"}
# Der Vertrag der Module nennt ihre Seiten (`APIRouter`, Entscheidung im Zuschnitt der Module);
# was er lädt, zählt nicht.
WEB_ALLOWED = {"moarcoal.registration"}


def imported_names(source: str) -> list[str]:
    """Alle Module, die der Quelltext importiert (absolut, wie geschrieben)."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.append(node.module)
    return found


def layer_breaches(source: str, route_prefixes: Collection[str]) -> list[str]:
    """Stellen, an denen Quelltext der Datenebene Web-Wissen trägt: ein Import aus FastAPI oder
    Starlette, oder ein Text, der mit einer Route der App beginnt (`/belege…`)."""
    found = [
        f"import {name}" for name in imported_names(source) if name.split(".")[0] in WEB_LIBRARIES
    ]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            match = re.match(r"/([^/?#{]+)", node.value)
            if match and match.group(1) in route_prefixes:
                found.append(f'"{node.value}"')
    return found


def route_prefixes(tmp_path: Path) -> set[str]:
    """Der erste Abschnitt jeder Route der App (`belege`, `aussteller`, `arbeit`, …)."""
    app = make_app(port=8000, data_dir=tmp_path)
    with warnings.catch_warnings():  # doppelte Operation-IDs der Weiterleitungen sind egal
        warnings.simplefilter("ignore")
        paths: Iterable[str] = app.openapi()["paths"]
    return {p.split("/")[1] for p in paths} - {""}


def source_of(module: str) -> Path | None:
    """Die Datei eines Moduls von MoarCoal; `None` außerhalb des Pakets."""
    if module != "moarcoal" and not module.startswith("moarcoal."):
        return None
    base = SRC.joinpath(*module.split(".")[1:])
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def web_loaders(start: Path) -> list[str]:
    """Die Module von MoarCoal, über die `start` (auch mittelbar) FastAPI oder Starlette lädt;
    `WEB_ALLOWED` wird nicht weiter verfolgt."""
    found: list[str] = []
    seen: set[str] = set()
    pending = imported_names(start.read_text(encoding="utf-8"))
    while pending:
        module = pending.pop()
        if module in seen or module in WEB_ALLOWED:
            continue
        seen.add(module)
        path = source_of(module)
        if path is None:
            continue
        names = imported_names(path.read_text(encoding="utf-8"))
        if any(n.split(".")[0] in WEB_LIBRARIES for n in names):
            found.append(module)
        pending += names
    return sorted(found)


def layer_files() -> list[Path]:
    return sorted(p for package in LAYER_PACKAGES for p in (SRC / package).rglob("*.py"))


def test_the_data_layer_knows_no_routes_and_no_fastapi(tmp_path: Path) -> None:
    """Prinzip 1: `storage/` und `values/` nennen keine Route und importieren FastAPI weder selbst
    noch über Seiten-Code; Adressen baut `links.py`."""
    prefixes = route_prefixes(tmp_path)
    offenders: dict[str, list[str]] = {}
    for path in layer_files():
        found = layer_breaches(path.read_text(encoding="utf-8"), prefixes)
        found += [f"lädt {m}" for m in web_loaders(path)]
        if found:
            offenders[path.relative_to(SRC).as_posix()] = found
    assert not offenders, f"Web-Wissen in der Datenebene: {offenders}"


def fastapi_importers(root: Path = SRC) -> list[str]:
    """Dateien außerhalb von `web/` und `modules/`, die FastAPI oder Starlette importieren.

    `modules/` führt die Seiten der Module (Router in der Anmeldung), nicht die Datenebene;
    `registration.py` ist der Vertrag, der `APIRouter` nennt.
    """
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if relative.parts[0] in ("web", "modules") or path.name == "registration.py":
            continue
        if any(n.split(".")[0] in WEB_LIBRARIES for n in imported_names(path.read_text("utf-8"))):
            found.append(relative.as_posix())
    return found


def test_outside_web_nothing_imports_fastapi() -> None:
    """Die Schicht steht am Pfad: FastAPI und Starlette kennt nur `web/` (und die Module samt
    Vertrag `registration.py`)."""
    assert fastapi_importers() == []


def test_the_fastapi_import_check_fails_on_an_injected_import(tmp_path: Path) -> None:
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "app.py").write_text("from fastapi import FastAPI\n", encoding="utf-8")
    (tmp_path / "documents.py").write_text("import fastapi.responses\n", encoding="utf-8")
    (tmp_path / "issuers.py").write_text("from starlette.requests import Request\n", "utf-8")
    (tmp_path / "defaults.py").write_text("import datetime\n", encoding="utf-8")
    assert fastapi_importers(tmp_path) == ["documents.py", "issuers.py"]


# Wer die Anbindung kennen darf: sie selbst, die Module (ihre Seiten), der Vertrag und der Start.
BINDING_KNOWERS = ("web", "modules", "registration.py", "__main__.py")


def binding_importers(root: Path = SRC) -> list[str]:
    """Dateien der Datenebene, die aus der Anbindung (`moarcoal.web`) importieren."""
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if relative.parts[0] in BINDING_KNOWERS:
            continue
        names = imported_names(path.read_text(encoding="utf-8"))
        if any(n == "moarcoal.web" or n.startswith("moarcoal.web.") for n in names):
            found.append(relative.as_posix())
    return found


def test_the_data_layer_imports_nothing_from_the_binding() -> None:
    """Prinzip 1: Die Datenebene kennt keine Adressen der Seiten; den Link eines Befunds baut die
    Anbindung aus Ziel und Verweisen (#154)."""
    assert binding_importers() == []


def test_the_binding_import_check_fails_on_an_injected_import(tmp_path: Path) -> None:
    for folder in ("web", "modules"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "pages.py").write_text("from moarcoal.web.links import x\n", "utf-8")
    (tmp_path / "__main__.py").write_text("from moarcoal.web.app import create_app\n", "utf-8")
    (tmp_path / "documents.py").write_text("from moarcoal.web.links import document_url\n", "utf-8")
    (tmp_path / "issuers.py").write_text("import moarcoal.web\n", encoding="utf-8")
    (tmp_path / "website.py").write_text("import moarcoal.website\n", encoding="utf-8")
    assert binding_importers(tmp_path) == ["documents.py", "issuers.py"]


def test_layer_check_finds_a_route_and_fastapi() -> None:
    prefixes = {"belege", "aussteller"}
    assert layer_breaches('href = "/belege"', prefixes) == ['"/belege"']
    assert layer_breaches('url = f"/aussteller/{x}"', prefixes) == ['"/aussteller/"']
    assert layer_breaches("from fastapi import Request", prefixes) == ["import fastapi"]
    assert layer_breaches('p = Path("/mnt", "c")\ns = "a/belege"', prefixes) == []


def test_route_prefixes_come_from_the_app(tmp_path: Path) -> None:
    assert {"belege", "aussteller", "befunde"} <= route_prefixes(tmp_path)


def test_every_kind_that_points_at_a_document_has_a_label(tmp_path: Path) -> None:
    """Am Dokument stehen die Einträge, die auf es verweisen, mit ihrer Bezeichnung; eine neue
    Einlesung eines Moduls erscheint so nie als Name im Code."""
    import_all_modules()
    store = open_store(tmp_path, [kind for m in MODULES for kind in m.kinds])
    labels = store.kind_labels()
    kinds = [k for k in all_kinds() if not k.__subclasses__()]  # ohne Basen wie `ReadInEntry`
    pointing = [k.__name__ for k in kinds if "document" in k.model_fields]
    assert pointing and [name for name in pointing if name not in labels] == []
