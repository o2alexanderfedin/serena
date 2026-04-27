"""Stage 2A — shared helpers for the 5 ergonomic facades + transaction commit.

Lifts the common preamble (workspace guard, capability resolution,
checkpoint recording, applier-result wrapping) out of each facade so each
Tool subclass ships ~80 LoC of orchestration instead of ~250 LoC of
boilerplate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from serena.refactoring.capabilities import CapabilityRecord
from serena.tools.scalpel_runtime import (
    ScalpelRuntime,
    parse_workspace_extra_paths,
)
from serena.tools.scalpel_schemas import (
    DiagnosticSeverityBreakdown,
    DiagnosticsDelta,
    ErrorCode,
    FailureInfo,
    RefactorResult,
)


FACADE_TO_CAPABILITY_ID: dict[str, dict[str, str]] = {
    "scalpel_split_file": {
        "rust": "rust.refactor.move.module",
        "python": "python.refactor.move.module",
    },
    "scalpel_extract": {
        "rust": "rust.refactor.extract.function",
        "python": "python.refactor.extract.function",
    },
    "scalpel_inline": {
        "rust": "rust.refactor.inline.function",
        "python": "python.refactor.inline.function",
    },
    "scalpel_rename": {
        "rust": "rust.refactor.rename",
        "python": "python.refactor.rename",
    },
    "scalpel_imports_organize": {
        "rust": "rust.source.organizeImports",
        "python": "python.source.organizeImports",
    },
}


def _empty_diagnostics_delta() -> DiagnosticsDelta:
    zero = DiagnosticSeverityBreakdown(error=0, warning=0, information=0, hint=0)
    return DiagnosticsDelta(
        before=zero, after=zero, new_findings=(), severity_breakdown=zero,
    )


def build_failure_result(
    *,
    code: ErrorCode,
    stage: str,
    reason: str,
    recoverable: bool = True,
    candidates: tuple[str, ...] = (),
) -> RefactorResult:
    """Construct a uniform failure RefactorResult for facade error paths."""
    return RefactorResult(
        applied=False,
        diagnostics_delta=_empty_diagnostics_delta(),
        failure=FailureInfo(
            stage=stage,
            reason=reason,
            code=code,
            recoverable=recoverable,
            candidates=candidates,
        ),
    )


def workspace_boundary_guard(
    *,
    file: str,
    project_root: Path,
    allow_out_of_workspace: bool,
) -> RefactorResult | None:
    """Q4 §11.8 enforcement — return a failure RefactorResult if outside.

    Mirrors ``SolidLanguageServer.is_in_workspace`` (ls.py:895). Returns
    ``None`` if in-workspace or ``allow_out_of_workspace=True``; otherwise a
    ``RefactorResult`` with WORKSPACE_BOUNDARY_VIOLATION.
    """
    if allow_out_of_workspace:
        return None
    from solidlsp.ls import SolidLanguageServer
    extras = parse_workspace_extra_paths()
    if SolidLanguageServer.is_in_workspace(
        target=file,
        roots=[str(project_root)],
        extra_paths=list(extras),
    ):
        return None
    return build_failure_result(
        code=ErrorCode.WORKSPACE_BOUNDARY_VIOLATION,
        stage="workspace_boundary_guard",
        reason=(
            f"File {file!r} is outside project_root {project_root!s}; "
            f"set allow_out_of_workspace=True with user permission, or "
            f"add the path to O2_SCALPEL_WORKSPACE_EXTRA_PATHS."
        ),
        recoverable=False,
    )


def resolve_capability_for_facade(
    facade_name: str,
    *,
    language: str,
    capability_id_override: str | None = None,
) -> CapabilityRecord | None:
    """Look up the CapabilityRecord this facade dispatches to."""
    catalog = ScalpelRuntime.instance().catalog()
    if capability_id_override is not None:
        target_id = capability_id_override
    else:
        target_id = FACADE_TO_CAPABILITY_ID.get(facade_name, {}).get(language)
        if target_id is None:
            return None
    for rec in catalog.records:
        if rec.id == target_id:
            return rec
    return None


def apply_workspace_edit_via_editor(
    workspace_edit: dict[str, Any],
    editor: Any,
) -> int:
    """Drive ``LanguageServerCodeEditor.apply_workspace_edit`` on the given edit."""
    return int(editor.apply_workspace_edit(workspace_edit))


def record_checkpoint_for_workspace_edit(
    workspace_edit: dict[str, Any],
    snapshot: dict[str, Any],
) -> str:
    """Push one checkpoint into ScalpelRuntime.checkpoint_store and return its id."""
    return ScalpelRuntime.instance().checkpoint_store().record(
        applied=workspace_edit,
        snapshot=snapshot,
    )


def coordinator_for_facade(
    *,
    language: str,
    project_root: Path,
):
    """Acquire the MultiServerCoordinator for ``language`` rooted at ``project_root``."""
    from solidlsp.ls_config import Language
    try:
        lang_enum = Language(language)
    except ValueError as exc:
        raise ValueError(
            f"coordinator_for_facade: unknown language {language!r}; "
            f"expected 'rust' or 'python'"
        ) from exc
    return ScalpelRuntime.instance().coordinator_for(lang_enum, project_root)


def attach_apply_source(cls: type) -> None:
    """Capture ``inspect.getsource(cls.apply)`` once and stash it as
    ``__wrapped_source__`` so downstream introspection is independent of
    ``linecache``. Idempotent. No-op when ``cls`` has no ``apply`` or when
    ``inspect.getsource`` raises (frozen / built-in / pyc-only)."""
    import inspect as _inspect
    fn = cls.__dict__.get("apply") or getattr(cls, "apply", None)
    if fn is None:
        return
    try:
        src = _inspect.getsource(fn)
    except (OSError, TypeError):
        return
    try:
        fn.__wrapped_source__ = src  # type: ignore[attr-defined]
    except (AttributeError, TypeError):
        return


def get_apply_source(cls: type) -> str:
    """Deterministic source for ``cls.apply``. Prefers the
    ``__wrapped_source__`` attribute attached by :func:`attach_apply_source`;
    falls back to ``inspect.getsource``. Returns ``""`` on failure."""
    import inspect as _inspect
    fn = getattr(cls, "apply", None)
    if fn is None:
        return ""
    captured = getattr(fn, "__wrapped_source__", None)
    if isinstance(captured, str) and captured:
        return captured
    try:
        return _inspect.getsource(fn)
    except (OSError, TypeError):
        return ""


__all__ = [
    "FACADE_TO_CAPABILITY_ID",
    "apply_workspace_edit_via_editor",
    "attach_apply_source",
    "build_failure_result",
    "coordinator_for_facade",
    "get_apply_source",
    "record_checkpoint_for_workspace_edit",
    "resolve_capability_for_facade",
    "workspace_boundary_guard",
]
