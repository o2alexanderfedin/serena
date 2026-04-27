"""v1.1 Stream 5 / Leaf 07 — `convert_from_relative_imports` helper.

Converts every relative import in a single Python module
(``from .x import y`` / ``from ..x import y`` / ``from . import x``) to
its absolute equivalent (``from pkg.x import y`` / ``from pkg import
x``) using rope's
``rope.refactor.importutils.ImportTools.relatives_to_absolutes``.

Returns a tuple ``(workspace_edit, summary)`` shaped like every other
helper in this package. The WorkspaceEdit is a single full-file
``TextEdit`` because rope's API hands us the whole post-rewrite source
as a string — we synthesize an LSP edit covering the entire file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def convert_from_relative_imports(
    *,
    file: str,
    project_root: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Build a WorkspaceEdit converting every relative import in ``file``.

    :param file: path of the Python module whose relative imports
        should be rewritten.
    :param project_root: package root to seed the rope ``Project``.
    :returns: ``(workspace_edit_or_none, status_dict)``. When the
        module already contains only absolute imports the rope output
        equals the input source — we return ``(None, status='skipped',
        reason='no_relative_imports')`` so the facade can record a
        no-op without touching disk.
    """
    target = _resolve(file, project_root)
    rel = target.relative_to(project_root)

    # Lazy-import rope so import-time failures (rope missing) become
    # facade-level skips instead of import-time crashes.
    try:
        from rope.base.project import Project
        from rope.refactor.importutils import ImportTools
    except ImportError as exc:
        return None, {
            "status": "skipped",
            "reason": "rope_unavailable",
            "detail": repr(exc),
        }

    project = Project(str(project_root))
    try:
        resource = project.get_resource(str(rel))
        pymodule = project.get_pymodule(resource)
        new_src = ImportTools(project).relatives_to_absolutes(pymodule)
    finally:
        project.close()

    if new_src is None:
        return None, {
            "status": "skipped",
            "reason": "rope_returned_none",
        }

    old_src = target.read_text(encoding="utf-8")
    if new_src == old_src:
        return None, {
            "status": "skipped",
            "reason": "no_relative_imports",
        }

    file_uri = target.as_uri()
    end_line, end_col = _end_position(old_src)
    workspace_edit = {
        "changes": {
            file_uri: [
                {
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": end_line, "character": end_col},
                    },
                    "newText": new_src,
                }
            ]
        }
    }
    return workspace_edit, {
        "status": "applied",
        "file": str(rel),
        "bytes_before": len(old_src),
        "bytes_after": len(new_src),
    }


def _resolve(file: str, project_root: Path) -> Path:
    candidate = Path(file)
    if not candidate.is_absolute():
        candidate = (project_root / candidate).resolve(strict=False)
    if not candidate.exists():
        raise FileNotFoundError(
            f"convert_from_relative_imports: file {file!r} not found "
            f"(resolved to {candidate})"
        )
    return candidate


def _end_position(src: str) -> tuple[int, int]:
    """LSP end-of-document position covering every byte of ``src``."""
    lines = src.splitlines(keepends=True)
    if not lines:
        return 0, 0
    last = lines[-1]
    if last.endswith(("\n", "\r")):
        # The file ends with a trailing newline — the end position is the
        # start of the line *after* the last visible line.
        return len(lines), 0
    return len(lines) - 1, len(last.rstrip("\n").rstrip("\r"))


__all__ = ["convert_from_relative_imports"]
