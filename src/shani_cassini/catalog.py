"""TOML-driven application catalog for the Shani Cassini.

Mirrors the proven catalog design from enigmars-utils: a frozen dataclass
(``CatalogApp``) describing a recommended application, a ``load_apps()``
function that scans a data directory for ``*.toml`` files, and an
``app_package_for()`` helper that resolves the native package name for a
given distro id (with an ``arch`` fallback, since Shanios is Arch-based).

Data files live in the repository-level ``data/catalog/`` directory — kept
out of the installed package, exactly as enigmars-utils does.
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Repository-level data directory: src/shani_cassini/catalog.py -> src/ -> repo root
DATA_DIR: Path = Path(__file__).resolve().parent.parent.parent / "data" / "catalog"


def _load_tomls(directory: Path) -> list[dict[str, Any]]:
    """Load every ``*.toml`` file in *directory* into a list of dicts.

    Mirrors enigmars-utils' ``_load_tomls``: sorted glob, binary open for
    ``tomllib``, skip non-dict documents, tag each with ``_source``.
    """
    if not directory.is_dir():
        return []
    docs: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.toml")):
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        if not isinstance(data, dict):
            continue
        data["_source"] = str(path)
        docs.append(data)
    return docs


@dataclass(frozen=True)
class CatalogApp:
    """A single recommended application entry from the catalog."""

    id: str
    title: str
    summary: str
    group: str
    packages: dict[str, str]
    flatpak: str | None


def load_apps() -> list[CatalogApp]:
    """Load all catalog applications from ``data/catalog/*.toml``.

    Skips documents without an ``id``.  Each ``[packages]`` table is
    coerced to ``dict[str, str]`` with empty values filtered out.
    """
    out: list[CatalogApp] = []
    for doc in _load_tomls(DATA_DIR):
        cid = str(doc.get("id") or "")
        if not cid:
            continue
        pkgs = doc.get("packages") or {}
        if not isinstance(pkgs, dict):
            pkgs = {}
        flatpak = doc.get("flatpak")
        out.append(
            CatalogApp(
                id=cid,
                title=str(doc.get("title") or cid),
                summary=str(doc.get("summary") or ""),
                group=str(doc.get("group") or "Apps"),
                packages={str(k): str(v) for k, v in pkgs.items() if v},
                flatpak=str(flatpak) if flatpak else None,
            )
        )
    return out


def app_package_for(app: CatalogApp, distro_id: str) -> str | None:
    """Resolve the native package name for *app* on *distro_id*.

    Looks up the exact distro key first, then falls back to ``"arch"``
    (Shanios is Arch-based).  Returns ``None`` when no package mapping
    exists for either.
    """
    pkgs = app.packages
    return pkgs.get(distro_id) or pkgs.get("arch")
