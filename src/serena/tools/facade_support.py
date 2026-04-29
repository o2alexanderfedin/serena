"""Stage 2A — shared helpers for the 5 ergonomic facades + transaction commit.

Lifts the common preamble (workspace guard, capability resolution,
checkpoint recording, applier-result wrapping) out of each facade so each
Tool subclass ships ~80 LoC of orchestration instead of ~250 LoC of
boilerplate.

v1.6 Plan 0 (PR 1) additionally lifts the low-level WorkspaceEdit
appliers (``_apply_workspace_edit_to_disk``,
``_apply_text_edits_to_file_uri``), the URI-to-path helper
(``_uri_to_path``), the action-resolver (``_resolve_winner_edit``), and
the snapshot sentinel (``_SNAPSHOT_NONEXISTENT``) here from
``scalpel_facades.py``. This breaks the
``scalpel_primitives <-> scalpel_facades`` import cycle so both modules
can ``from .facade_support import ...`` cleanly at the top.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

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


# ---------------------------------------------------------------------------
# v1.6 Plan 0 — sentinel + low-level appliers lifted from scalpel_facades.
# ---------------------------------------------------------------------------


# Sentinel value carried in ``checkpoint.snapshot[uri]`` to mean "this URI
# did not exist on disk pre-edit". Plan 1 (v1.6 PR 2) populates real
# snapshot content; Plan 0 only lifts the sentinel so primitives can
# import it without going through the facade module.
_SNAPSHOT_NONEXISTENT = "__O2_SCALPEL_SNAPSHOT_NONEXISTENT__"


def _uri_to_path(uri: str) -> Path | None:
    """Convert a ``file://`` URI to a ``Path`` or return ``None``.

    Plan 0 lift: the inline ``urlparse(uri).path`` snippet was duplicated
    twice in ``scalpel_facades.py`` (the standard applier and the
    markdown applier). Single source of truth here.
    """
    if not uri.startswith("file://"):
        return None
    parsed = urlparse(uri)
    return Path(unquote(parsed.path))


def _lsp_position_to_offset(lines: list[str], line: int, character: int) -> int:
    """Convert an LSP (line, character) to a flat offset in the joined source."""
    if line < 0:
        return 0
    if line >= len(lines):
        return sum(len(lll) for lll in lines)
    prefix = sum(len(lines[i]) for i in range(line))
    target_line = lines[line]
    # Strip trailing newline for the column clamp; columns are over visible chars.
    visible = target_line.rstrip("\n").rstrip("\r")
    return prefix + min(character, len(visible))


def _splice_text_edit(source: str, edit: dict[str, Any]) -> str:
    """Replace ``source`` between LSP positions with ``edit['newText']``."""
    start = edit["range"]["start"]
    end = edit["range"]["end"]
    new_text = edit["newText"]
    lines = source.splitlines(keepends=True)
    start_offset = _lsp_position_to_offset(lines, start["line"], start["character"])
    end_offset = _lsp_position_to_offset(lines, end["line"], end["character"])
    return source[:start_offset] + new_text + source[end_offset:]


def _apply_text_edits_to_file_uri(uri: str, edits: list[dict[str, Any]]) -> int:
    """Resolve ``uri`` to a local path and apply the edits in descending order.

    Returns the count of edits applied (0 when the URI isn't a ``file://``
    URI or the target file doesn't exist on disk).
    """
    target = _uri_to_path(uri)
    if target is None:
        return 0
    if not edits:
        return 0
    if not target.exists():
        return 0
    source = target.read_text(encoding="utf-8")
    sorted_edits = sorted(
        edits,
        key=lambda e: (
            e["range"]["start"]["line"], e["range"]["start"]["character"],
        ),
        reverse=True,
    )
    for edit in sorted_edits:
        source = _splice_text_edit(source, edit)
    target.write_text(source, encoding="utf-8")
    return len(sorted_edits)


def _apply_workspace_edit_to_disk(workspace_edit: dict[str, Any]) -> int:
    """Apply an LSP-spec WorkspaceEdit to the filesystem (v0.3.0).

    Walks both the ``changes`` (dict shape) and ``documentChanges`` (array
    shape) forms; routes every TextDocumentEdit's ``edits`` list through
    :func:`_apply_text_edits_to_file_uri` which sorts by descending position
    so earlier edits don't invalidate later positions.

    Resource operations (CreateFile / RenameFile / DeleteFile) inside
    ``documentChanges`` are recognised but skipped — they ship in v1.1
    alongside resource-management auditing.

    Returns the count of TextEdits actually applied (excluding skipped
    non-file URIs and missing target files). Caller uses the return value
    to distinguish ``applied=True`` (count > 0) from ``no_op`` (count == 0).
    """
    applied = 0
    # changes shape: {uri: [TextEdit, ...]}
    for uri, edits in (workspace_edit.get("changes") or {}).items():
        applied += _apply_text_edits_to_file_uri(uri, edits or [])
    # documentChanges shape: [TextDocumentEdit | CreateFile | RenameFile | DeleteFile, ...]
    for dc in workspace_edit.get("documentChanges") or []:
        if not isinstance(dc, dict):
            continue
        if "kind" in dc:
            # Resource op — skip per v1.1 deferral.
            continue
        text_doc = dc.get("textDocument") or {}
        uri = text_doc.get("uri")
        if not isinstance(uri, str):
            continue
        applied += _apply_text_edits_to_file_uri(uri, dc.get("edits") or [])
    return applied


def _resolve_winner_edit(coord: Any, winner: Any) -> dict[str, Any] | None:
    """Best-effort extract of the resolved WorkspaceEdit for ``winner``.

    Looks up the action by id via ``coord.get_action_edit`` (added in
    v0.3.0). Returns ``None`` when the coord doesn't expose the lookup
    (legacy fakes) or the id isn't tracked.
    """
    aid = getattr(winner, "id", None) or getattr(winner, "action_id", None)
    if not isinstance(aid, str):
        return None
    fn = getattr(coord, "get_action_edit", None)
    if not callable(fn):
        return None
    edit = fn(aid)
    return edit if isinstance(edit, dict) else None


def capture_pre_edit_snapshot(workspace_edit: dict[str, Any]) -> dict[str, str]:
    """Read pre-edit file bytes for every URI touched by ``workspace_edit``.

    v1.6 Plan 1 (PR 2) shifts checkpoint snapshots from the v0.2.0 empty
    ``snapshot={}`` placeholder to honest "what was there before" content
    so :class:`serena.refactoring.checkpoints.CheckpointStore` can support
    real rollback in v1.7.

    Walks both edit shapes:

    - ``changes`` (``{uri: [TextEdit]}``) — every URI's pre-edit content
      is read off disk via :func:`_uri_to_path` + ``Path.read_text``.
    - ``documentChanges`` (heterogeneous list):

      - ``TextDocumentEdit`` (no ``kind``): same as a ``changes`` entry.
      - ``CreateFile`` (``kind="create"``): record
        :data:`_SNAPSHOT_NONEXISTENT` for the new URI — the pre-state was
        "doesn't exist".
      - ``DeleteFile`` (``kind="delete"``): record
        :data:`_SNAPSHOT_NONEXISTENT`. The LSP delete-op carries no payload
        and the post-state is "doesn't exist"; a future rollback recreates
        the file from the inverse-edit's pre-bytes (lifted into the
        snapshot path here).
      - ``RenameFile`` (``kind="rename"``): snapshot the OLD URI's pre-edit
        content. The NEW URI didn't exist pre-edit and isn't recorded.

    Files that resolve to a path but are missing on disk fall back to
    :data:`_SNAPSHOT_NONEXISTENT` (matches the "create" semantics for
    edits that materialise a brand-new file via TextDocumentEdit).

    Returns ``{}`` for an empty / malformed edit. Best-effort: I/O errors
    are surfaced as the sentinel rather than crashing the apply path.
    """
    snapshot: dict[str, str] = {}
    # changes shape: {uri: [TextEdit, ...]}
    for uri in (workspace_edit.get("changes") or {}).keys():
        snapshot[uri] = _read_pre_edit_or_sentinel(uri)
    # documentChanges shape: heterogeneous list.
    for dc in workspace_edit.get("documentChanges") or []:
        if not isinstance(dc, dict):
            continue
        kind = dc.get("kind")
        if kind == "create":
            uri = dc.get("uri")
            if isinstance(uri, str):
                snapshot[uri] = _SNAPSHOT_NONEXISTENT
        elif kind == "delete":
            uri = dc.get("uri")
            if isinstance(uri, str):
                snapshot[uri] = _SNAPSHOT_NONEXISTENT
        elif kind == "rename":
            old_uri = dc.get("oldUri")
            if isinstance(old_uri, str):
                snapshot[old_uri] = _read_pre_edit_or_sentinel(old_uri)
        else:
            # TextDocumentEdit: no ``kind`` key.
            text_doc = dc.get("textDocument") or {}
            uri = text_doc.get("uri")
            if isinstance(uri, str):
                snapshot[uri] = _read_pre_edit_or_sentinel(uri)
    return snapshot


def _read_pre_edit_or_sentinel(uri: str) -> str:
    """Read the file at ``uri`` or return :data:`_SNAPSHOT_NONEXISTENT`.

    Helper for :func:`capture_pre_edit_snapshot`: non-``file://`` URIs,
    missing files, and read errors all collapse onto the sentinel so the
    snapshot dict stays a uniform ``{uri: str}`` shape.
    """
    target = _uri_to_path(uri)
    if target is None or not target.exists():
        return _SNAPSHOT_NONEXISTENT
    try:
        return target.read_text(encoding="utf-8")
    except OSError:
        return _SNAPSHOT_NONEXISTENT


def apply_action_and_checkpoint(
    coord: Any,
    action: Any,
) -> tuple[str, dict[str, Any]]:
    """Resolve, snapshot, apply, and checkpoint a winner action in one step.

    Replaces the 5-line snippet duplicated across 9 facade dispatch sites:

        edit = _resolve_winner_edit(coord, action)
        if isinstance(edit, dict) and edit:
            _apply_workspace_edit_to_disk(edit)
        else:
            edit = {"changes": {}}
        cid = record_checkpoint_for_workspace_edit(edit, snapshot={})

    The new behaviour, encapsulated here:

    1. Resolve the WorkspaceEdit via :func:`_resolve_winner_edit`.
    2. If an edit was resolved, capture the pre-edit snapshot via
       :func:`capture_pre_edit_snapshot` BEFORE applying so the snapshot
       is honest about "what was there before".
    3. Apply via :func:`_apply_workspace_edit_to_disk` when an edit
       resolved; otherwise fall through with an empty edit.
    4. Always record a checkpoint via
       :func:`record_checkpoint_for_workspace_edit` (matching the v0.2.0
       contract where ``applied=True`` always carries a non-empty
       ``checkpoint_id``, even for legacy fakes whose synthetic action
       ids don't resolve to a real edit).

    :returns: ``(checkpoint_id, applied_edit)``. ``applied_edit`` is the
      resolved edit when available, else ``{"changes": {}}``. The
      checkpoint id is always non-empty.
    """
    edit = _resolve_winner_edit(coord, action)
    if isinstance(edit, dict) and edit:
        snapshot = capture_pre_edit_snapshot(edit)
        _apply_workspace_edit_to_disk(edit)
    else:
        # Resolve failed (legacy fake, untracked id, non-dict). Fall back to
        # the v0.2.0 empty-edit checkpoint so callers still emit a
        # non-empty ``checkpoint_id`` and downstream rollback gets a
        # well-formed (empty) record rather than a missing one.
        edit = {"changes": {}}
        snapshot = {}
    cid = record_checkpoint_for_workspace_edit(edit, snapshot=snapshot)
    return (cid, edit)


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
    """Acquire the MultiServerCoordinator for ``language`` rooted at ``project_root``.

    Supported languages: any value of ``solidlsp.ls_config.Language``. v1.5
    Phase 2 added ``"java"`` so ``ScalpelExtractTool`` and the new
    ``ScalpelGenerateConstructorTool`` / ``ScalpelOverrideMethodsTool`` can
    route through jdtls.
    """
    from solidlsp.ls_config import Language
    try:
        lang_enum = Language(language)
    except ValueError as exc:
        raise ValueError(
            f"coordinator_for_facade: unknown language {language!r}; "
            f"expected a Language enum value (e.g. 'rust', 'python', 'java')"
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
    "_SNAPSHOT_NONEXISTENT",
    "_apply_text_edits_to_file_uri",
    "_apply_workspace_edit_to_disk",
    "_lsp_position_to_offset",
    "_resolve_winner_edit",
    "_splice_text_edit",
    "_uri_to_path",
    "apply_action_and_checkpoint",
    "apply_workspace_edit_via_editor",
    "attach_apply_source",
    "build_failure_result",
    "capture_pre_edit_snapshot",
    "coordinator_for_facade",
    "get_apply_source",
    "record_checkpoint_for_workspace_edit",
    "resolve_capability_for_facade",
    "workspace_boundary_guard",
]
