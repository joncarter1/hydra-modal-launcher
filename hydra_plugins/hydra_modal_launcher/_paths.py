"""Path discovery helpers shared between the launcher and the image builder.

Lives in its own module to avoid pulling ``modal_launcher``'s hydra-core
imports into ``_modal_app``'s pure helper surface, and to give the path
helpers a single home.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


_PROJECT_ROOT_MARKERS = ("pyproject.toml", "setup.py", "setup.cfg", ".git")


def _detect_project_root(start_path: Path) -> Optional[Path]:
    """Walk up from ``start_path`` looking for a project-root marker file.

    Returns the first ancestor directory containing any of
    ``pyproject.toml`` / ``setup.py`` / ``setup.cfg`` / ``.git``, or ``None``
    if the filesystem root is hit before a marker is found.
    """
    cur = start_path.resolve()
    while True:
        if any((cur / m).exists() for m in _PROJECT_ROOT_MARKERS):
            return cur
        if cur.parent == cur:
            return None
        cur = cur.parent


def _resolve_against_project_root(path: str) -> str:
    """Resolve a config-supplied path with a small dose of project-aware DWIM.

    Behaviour, in order:
    - ``~`` is expanded.
    - Absolute paths are returned unchanged.
    - Relative paths that exist relative to CWD are returned unchanged (so
      Modal's default CWD-relative semantics still win when both paths exist).
    - Otherwise, walk up from CWD looking for a project-root marker. If found
      and the file exists relative to that root, return the absolute path.
    - On any miss, return the original string so Modal raises a clear
      ``FileNotFoundError`` at build time rather than us silently swallowing it.
    """
    expanded = os.path.expanduser(path)
    p = Path(expanded)
    if p.is_absolute() or p.exists():
        return str(p)
    root = _detect_project_root(Path.cwd())
    if root is not None:
        candidate = root / p
        if candidate.exists():
            return str(candidate)
    return path
