"""Per-(language, project_root) LSP pool (Stage 1C §14.1 file 8).

The pool sits behind the deferred-loading surface (§6.10 / §12.2): a language
facade calls ``pool.acquire(LspPoolKey(language, project_root))`` and gets a
fully-initialised ``SolidLanguageServer`` whose underlying child process is
spawned on first use, kept warm across calls, recycled when the pre-ping
health probe fails, and reaped after ``O2_SCALPEL_LSP_IDLE_SHUTDOWN_SECONDS``
of inactivity. The §16.1 RAM ceiling is enforced before every spawn; the
guard refuses with ``WaitingForLspBudget`` when over budget rather than
crashing the user's editor.

This module is added incrementally across T1..T8 — see PROGRESS.md.
T1 lands ``LspPoolKey`` only; later tasks layer the lifecycle on top.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LspPoolKey:
    """Canonical (language, project_root) tuple used as a pool dict key.

    ``project_root`` is canonicalised at construction via ``Path.resolve(strict=False)``;
    relative paths, ``~`` expansion, symlinks, and trailing slashes all collapse
    to the same key.

    :param language: the canonical language identifier ("rust", "python", ...).
    :param project_root: the absolute or relative path to the project root.
    """

    language: str
    project_root: str
    project_root_path: Path = field(init=False, repr=False, compare=False, hash=False)

    def __post_init__(self) -> None:
        # frozen=True forbids attribute assignment; use object.__setattr__ to
        # populate the derived field at construction.
        resolved = Path(self.project_root).expanduser().resolve(strict=False)
        object.__setattr__(self, "project_root_path", resolved)
        # Re-stamp project_root with the canonical str so equality/hash match
        # across the original input forms.
        object.__setattr__(self, "project_root", str(resolved))
