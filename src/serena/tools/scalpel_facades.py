"""Stage 2A — 5 ergonomic intent facades + scalpel_transaction_commit.

Each Tool subclass composes Stage 1G primitives (catalog -> coordinator
-> applier -> checkpoint) into one named MCP entry. Docstrings on each
``apply`` are <=30 words (router signage, §5.4).
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Literal, cast

from serena.tools.facade_support import (
    attach_apply_source,
    build_failure_result,
    coordinator_for_facade,
    record_checkpoint_for_workspace_edit,
    workspace_boundary_guard,
)
from serena.tools.scalpel_runtime import ScalpelRuntime
from serena.tools.scalpel_schemas import (
    DiagnosticSeverityBreakdown,
    DiagnosticsDelta,
    ErrorCode,
    LspOpStat,
    RefactorResult,
    _LanguageFinding as LanguageFinding,
)
from serena.tools.tools_base import Tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_diagnostics_delta() -> DiagnosticsDelta:
    zero = DiagnosticSeverityBreakdown(error=0, warning=0, information=0, hint=0)
    return DiagnosticsDelta(
        before=zero, after=zero, new_findings=(), severity_breakdown=zero,
    )


def _infer_language(file: str, explicit: str | None) -> str:
    if explicit is not None:
        return explicit
    suffix = Path(file).suffix
    if suffix == ".rs":
        return "rust"
    if suffix in (".py", ".pyi"):
        return "python"
    return "unknown"


def _build_python_rope_bridge(project_root: Path):
    """Construct an in-process Rope bridge — extracted to a top-level so tests
    can patch it without monkey-patching __init__ paths.
    """
    from serena.refactoring.python_strategy import _RopeBridge
    return _RopeBridge(project_root)


def _merge_workspace_edits(
    edits: list[dict[str, Any]],
) -> dict[str, Any]:
    """Combine N WorkspaceEdits into one by concatenating documentChanges."""
    out: dict[str, Any] = {"documentChanges": []}
    for e in edits:
        for dc in e.get("documentChanges", []):
            out["documentChanges"].append(dc)
        for path, hunks in e.get("changes", {}).items():
            out.setdefault("changes", {}).setdefault(path, []).extend(hunks)
    return out


def _run_async(coro):
    """Drive an async coroutine to completion in a tool's sync `apply` path."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return asyncio.run_coroutine_threadsafe(coro, loop).result()
    except RuntimeError:
        pass
    return asyncio.new_event_loop().run_until_complete(coro)


def _apply_workspace_edit_to_disk(workspace_edit: dict[str, Any]) -> int:
    """Apply an LSP-spec WorkspaceEdit to the filesystem (v0.3.0).

    Walks both the ``changes`` (dict shape) and ``documentChanges`` (array
    shape) forms; routes every TextDocumentEdit's ``edits`` list through
    ``_apply_text_edits_to_file`` which sorts by descending position so
    earlier edits don't invalidate later positions.

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


def _apply_text_edits_to_file_uri(uri: str, edits: list[dict[str, Any]]) -> int:
    """Resolve ``uri`` to a local path and apply the edits in descending order.

    Returns the count of edits applied (0 when the URI isn't a ``file://``
    URI or the target file doesn't exist on disk).
    """
    if not uri.startswith("file://"):
        return 0
    if not edits:
        return 0
    from urllib.parse import urlparse, unquote
    parsed = urlparse(uri)
    target = Path(unquote(parsed.path))
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


def _splice_text_edit(source: str, edit: dict[str, Any]) -> str:
    """Replace ``source`` between LSP positions with ``edit['newText']``."""
    start = edit["range"]["start"]
    end = edit["range"]["end"]
    new_text = edit["newText"]
    lines = source.splitlines(keepends=True)
    start_offset = _lsp_position_to_offset(lines, start["line"], start["character"])
    end_offset = _lsp_position_to_offset(lines, end["line"], end["character"])
    return source[:start_offset] + new_text + source[end_offset:]


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


# ---------------------------------------------------------------------------
# T3: ScalpelSplitFileTool
# ---------------------------------------------------------------------------


class ScalpelSplitFileTool(Tool):
    """Split a source file into N modules by moving named symbols."""

    def apply(
        self,
        file: str,
        groups: dict[str, list[str]],
        parent_layout: Literal["package", "file"] = "package",
        keep_in_original: list[str] | None = None,
        reexport_policy: Literal[
            "preserve_public_api", "none", "explicit_list"
        ] = "preserve_public_api",
        explicit_reexports: list[str] | None = None,
        allow_partial: bool = False,
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Split a source file into N modules by moving named symbols. Atomic.

        :param file: source file to split.
        :param groups: target_module -> [symbol_name, ...] mapping.
        :param parent_layout: 'package' or 'file'.
        :param keep_in_original: symbols to keep in the original file.
        :param reexport_policy: 'preserve_public_api', 'none', or 'explicit_list'.
        :param explicit_reexports: when policy=explicit_list, the names to re-export.
        :param allow_partial: when True, surface partial successes.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del parent_layout, keep_in_original, reexport_policy
        del explicit_reexports, allow_partial, preview_token
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        guard = workspace_boundary_guard(
            file=file, project_root=project_root,
            allow_out_of_workspace=allow_out_of_workspace,
        )
        if guard is not None:
            return guard.model_dump_json(indent=2)
        if not groups:
            return RefactorResult(
                applied=False, no_op=True,
                diagnostics_delta=_empty_diagnostics_delta(),
            ).model_dump_json(indent=2)
        lang = _infer_language(file, language)
        if lang not in ("rust", "python"):
            return build_failure_result(
                code=ErrorCode.INVALID_ARGUMENT,
                stage="scalpel_split_file",
                reason=f"Cannot infer language from {file!r}; pass language=.",
                recoverable=False,
            ).model_dump_json(indent=2)
        if lang == "python":
            return self._split_python(
                file=file, groups=groups,
                project_root=project_root, dry_run=dry_run,
            ).model_dump_json(indent=2)
        return self._split_rust(
            file=file, groups=groups,
            project_root=project_root, dry_run=dry_run,
        ).model_dump_json(indent=2)

    def _split_python(
        self,
        *,
        file: str,
        groups: dict[str, list[str]],
        project_root: Path,
        dry_run: bool,
    ) -> RefactorResult:
        bridge = _build_python_rope_bridge(project_root)
        edits: list[dict[str, Any]] = []
        t0 = time.monotonic()
        try:
            rel = str(Path(file).relative_to(project_root))
            for group_name in groups.keys():
                target_rel = f"{group_name}.py"
                edits.append(bridge.move_module(rel, target_rel))
        finally:
            try:
                bridge.close()
            except Exception:
                pass
        merged = _merge_workspace_edits(edits)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if dry_run:
            return RefactorResult(
                applied=False, no_op=False,
                diagnostics_delta=_empty_diagnostics_delta(),
                preview_token=f"pv_split_{int(time.time())}",
                duration_ms=elapsed_ms,
            )
        cid = record_checkpoint_for_workspace_edit(merged, snapshot={})
        return RefactorResult(
            applied=True,
            diagnostics_delta=_empty_diagnostics_delta(),
            checkpoint_id=cid,
            duration_ms=elapsed_ms,
            lsp_ops=(LspOpStat(
                method="rope.refactor.move",
                server="pylsp-rope",
                count=len(groups),
                total_ms=elapsed_ms,
            ),),
        )

    def _split_rust(
        self,
        *,
        file: str,
        groups: dict[str, list[str]],
        project_root: Path,
        dry_run: bool,
    ) -> RefactorResult:
        del groups
        coord = coordinator_for_facade(language="rust", project_root=project_root)
        t0 = time.monotonic()
        actions = _run_async(coord.merge_code_actions(
            file=file,
            start={"line": 0, "character": 0},
            end={"line": 0, "character": 0},
            only=["refactor.extract.module"],
        ))
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if not actions:
            return build_failure_result(
                code=ErrorCode.SYMBOL_NOT_FOUND,
                stage="scalpel_split_file",
                reason="No refactor.extract.module actions surfaced.",
            )
        if dry_run:
            return RefactorResult(
                applied=False, no_op=False,
                diagnostics_delta=_empty_diagnostics_delta(),
                preview_token=f"pv_split_{int(time.time())}",
                duration_ms=elapsed_ms,
            )
        # v0.3.0 facade-application: apply the resolved WorkspaceEdit if available.
        edit = _resolve_winner_edit(coord, actions[0])
        if isinstance(edit, dict) and edit:
            _apply_workspace_edit_to_disk(edit)
        else:
            edit = {"changes": {}}
        cid = record_checkpoint_for_workspace_edit(workspace_edit=edit, snapshot={})
        return RefactorResult(
            applied=True,
            diagnostics_delta=_empty_diagnostics_delta(),
            checkpoint_id=cid,
            duration_ms=elapsed_ms,
            lsp_ops=(LspOpStat(
                method="textDocument/codeAction",
                server="rust-analyzer",
                count=len(actions),
                total_ms=elapsed_ms,
            ),),
        )


# ---------------------------------------------------------------------------
# T4: ScalpelExtractTool
# ---------------------------------------------------------------------------


_EXTRACT_TARGET_TO_KIND: dict[str, str] = {
    "function": "refactor.extract.function",
    "variable": "refactor.extract.variable",
    "constant": "refactor.extract.constant",
    "static": "refactor.extract.static",
    "type_alias": "refactor.extract.type_alias",
    "module": "refactor.extract.module",
}


class ScalpelExtractTool(Tool):
    """Extract a symbol/selection into a new variable/function/module/type."""

    def apply(
        self,
        file: str,
        range: dict[str, Any] | None = None,
        name_path: str | None = None,
        target: Literal[
            "variable", "function", "constant", "static", "type_alias", "module"
        ] = "function",
        new_name: str = "extracted",
        visibility: Literal["private", "pub_crate", "pub"] = "private",
        similar: bool = False,
        global_scope: bool = False,
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Extract a selection into a new variable, function, module, or type.
        Pick `target` to choose. Atomic.

        :param file: source file containing the selection or symbol.
        :param range: optional LSP Range; one of range or name_path required.
        :param name_path: optional Serena name-path.
        :param target: extraction target enum.
        :param new_name: name for the extracted item.
        :param visibility: Rust visibility prefix on the new item.
        :param similar: when True (Python/Rope), extract similar expressions too.
        :param global_scope: extract to module scope (Python only).
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del new_name, visibility, similar, global_scope, preview_token, name_path
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        guard = workspace_boundary_guard(
            file=file, project_root=project_root,
            allow_out_of_workspace=allow_out_of_workspace,
        )
        if guard is not None:
            return guard.model_dump_json(indent=2)
        if range is None:
            return build_failure_result(
                code=ErrorCode.INVALID_ARGUMENT,
                stage="scalpel_extract",
                reason="One of range= or name_path= is required.",
                recoverable=False,
            ).model_dump_json(indent=2)
        kind = _EXTRACT_TARGET_TO_KIND.get(target)
        if kind is None:
            return build_failure_result(
                code=ErrorCode.INVALID_ARGUMENT,
                stage="scalpel_extract",
                reason=f"Unknown target {target!r}; expected one of {sorted(_EXTRACT_TARGET_TO_KIND)}.",
                recoverable=False,
            ).model_dump_json(indent=2)
        lang = _infer_language(file, language)
        if lang not in ("rust", "python"):
            return build_failure_result(
                code=ErrorCode.INVALID_ARGUMENT,
                stage="scalpel_extract",
                reason=f"Cannot infer language from {file!r}; pass language=.",
                recoverable=False,
            ).model_dump_json(indent=2)
        coord = coordinator_for_facade(language=lang, project_root=project_root)
        rng = range
        t0 = time.monotonic()
        actions = _run_async(coord.merge_code_actions(
            file=file,
            start=rng["start"],
            end=rng["end"],
            only=[kind],
        ))
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if not actions:
            return build_failure_result(
                code=ErrorCode.SYMBOL_NOT_FOUND,
                stage="scalpel_extract",
                reason=f"No {kind} actions surfaced for {file!r}.",
            ).model_dump_json(indent=2)
        if dry_run:
            return RefactorResult(
                applied=False, no_op=False,
                diagnostics_delta=_empty_diagnostics_delta(),
                preview_token=f"pv_extract_{int(time.time())}",
                duration_ms=elapsed_ms,
            ).model_dump_json(indent=2)
        # v0.3.0 facade-application: apply the resolved WorkspaceEdit if available.
        edit = _resolve_winner_edit(coord, actions[0])
        if isinstance(edit, dict) and edit:
            _apply_workspace_edit_to_disk(edit)
        else:
            edit = {"changes": {}}
        cid = record_checkpoint_for_workspace_edit(workspace_edit=edit, snapshot={})
        return RefactorResult(
            applied=True,
            diagnostics_delta=_empty_diagnostics_delta(),
            checkpoint_id=cid,
            duration_ms=elapsed_ms,
            lsp_ops=(LspOpStat(
                method="textDocument/codeAction",
                server=actions[0].provenance if actions else "unknown",
                count=len(actions),
                total_ms=elapsed_ms,
            ),),
        ).model_dump_json(indent=2)


# ---------------------------------------------------------------------------
# T5: ScalpelInlineTool
# ---------------------------------------------------------------------------


_INLINE_TARGET_TO_KIND: dict[str, str] = {
    "call": "refactor.inline.call",
    "variable": "refactor.inline.variable",
    "type_alias": "refactor.inline.type_alias",
    "macro": "refactor.inline.macro",
    "const": "refactor.inline.const",
}


class ScalpelInlineTool(Tool):
    """Inline a function/variable/type alias at definition or call sites."""

    def apply(
        self,
        file: str,
        name_path: str | None = None,
        position: dict[str, Any] | None = None,
        target: Literal["call", "variable", "type_alias", "macro", "const"] = "call",
        scope: Literal["single_call_site", "all_callers"] = "single_call_site",
        remove_definition: bool = True,
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Inline a function, variable, or type alias at definition or
        call-sites. Pick `target`. Atomic.

        :param file: source file containing the definition or call.
        :param name_path: optional Serena name-path.
        :param position: optional LSP Position at the call site.
        :param target: 'call' | 'variable' | 'type_alias' | 'macro' | 'const'.
        :param scope: 'single_call_site' or 'all_callers'.
        :param remove_definition: drop the original definition after inlining.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del name_path, remove_definition, preview_token
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        guard = workspace_boundary_guard(
            file=file, project_root=project_root,
            allow_out_of_workspace=allow_out_of_workspace,
        )
        if guard is not None:
            return guard.model_dump_json(indent=2)
        kind = _INLINE_TARGET_TO_KIND.get(target)
        if kind is None:
            return build_failure_result(
                code=ErrorCode.INVALID_ARGUMENT,
                stage="scalpel_inline",
                reason=f"Unknown target {target!r}; expected one of {sorted(_INLINE_TARGET_TO_KIND)}.",
                recoverable=False,
            ).model_dump_json(indent=2)
        if scope == "single_call_site" and position is None:
            return build_failure_result(
                code=ErrorCode.INVALID_ARGUMENT,
                stage="scalpel_inline",
                reason="scope=single_call_site requires position=.",
                recoverable=False,
            ).model_dump_json(indent=2)
        lang = _infer_language(file, language)
        if lang not in ("rust", "python"):
            return build_failure_result(
                code=ErrorCode.INVALID_ARGUMENT,
                stage="scalpel_inline",
                reason=f"Cannot infer language from {file!r}; pass language=.",
                recoverable=False,
            ).model_dump_json(indent=2)
        coord = coordinator_for_facade(language=lang, project_root=project_root)
        pos = position or {"line": 0, "character": 0}
        rng = {"start": pos, "end": pos}
        t0 = time.monotonic()
        actions = _run_async(coord.merge_code_actions(
            file=file, start=rng["start"], end=rng["end"], only=[kind],
        ))
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if not actions:
            return build_failure_result(
                code=ErrorCode.SYMBOL_NOT_FOUND,
                stage="scalpel_inline",
                reason=f"No {kind} actions surfaced for {file!r}.",
            ).model_dump_json(indent=2)
        if dry_run:
            return RefactorResult(
                applied=False, no_op=False,
                diagnostics_delta=_empty_diagnostics_delta(),
                preview_token=f"pv_inline_{int(time.time())}",
                duration_ms=elapsed_ms,
            ).model_dump_json(indent=2)
        # v0.3.0 facade-application: apply the resolved WorkspaceEdit if available.
        edit = _resolve_winner_edit(coord, actions[0])
        if isinstance(edit, dict) and edit:
            _apply_workspace_edit_to_disk(edit)
        else:
            edit = {"changes": {}}
        cid = record_checkpoint_for_workspace_edit(workspace_edit=edit, snapshot={})
        return RefactorResult(
            applied=True,
            diagnostics_delta=_empty_diagnostics_delta(),
            checkpoint_id=cid,
            duration_ms=elapsed_ms,
            lsp_ops=(LspOpStat(
                method="textDocument/codeAction",
                server=actions[0].provenance if actions else "unknown",
                count=len(actions),
                total_ms=elapsed_ms,
            ),),
        ).model_dump_json(indent=2)


# ---------------------------------------------------------------------------
# T6: ScalpelRenameTool
# ---------------------------------------------------------------------------


def _looks_like_module_name_path(name_path: str, file: str) -> bool:
    """Heuristic: name_path matches the file's basename (no separators)."""
    if "/" in name_path or "." in name_path or "::" in name_path:
        return False
    base = Path(file).stem
    return name_path == base


class ScalpelRenameTool(Tool):
    """Rename a symbol everywhere it is referenced. Cross-file."""

    def apply(
        self,
        file: str,
        name_path: str,
        new_name: str,
        also_in_strings: bool = False,
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Rename a symbol everywhere it is referenced. Cross-file.
        Returns checkpoint_id. Hallucination-resistant on name-paths.

        :param file: file containing the definition (or any reference).
        :param name_path: Serena name-path of the symbol (e.g. 'mod::Sym').
        :param new_name: replacement name.
        :param also_in_strings: also rewrite string-literal occurrences.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del also_in_strings, preview_token
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        guard = workspace_boundary_guard(
            file=file, project_root=project_root,
            allow_out_of_workspace=allow_out_of_workspace,
        )
        if guard is not None:
            return guard.model_dump_json(indent=2)
        lang = _infer_language(file, language)
        if lang not in ("rust", "python"):
            return build_failure_result(
                code=ErrorCode.INVALID_ARGUMENT,
                stage="scalpel_rename",
                reason=f"Cannot infer language from {file!r}; pass language=.",
                recoverable=False,
            ).model_dump_json(indent=2)
        # Module-rename short-circuit: prefer Rope (preserves __all__).
        if lang == "python" and _looks_like_module_name_path(name_path, file):
            return self._rename_python_module(
                file=file, new_name=new_name,
                project_root=project_root, dry_run=dry_run,
            ).model_dump_json(indent=2)
        coord = coordinator_for_facade(language=lang, project_root=project_root)
        t0 = time.monotonic()
        position = self._resolve_symbol_position(
            coord=coord, file=file, name_path=name_path,
        )
        if position is None:
            return build_failure_result(
                code=ErrorCode.SYMBOL_NOT_FOUND,
                stage="scalpel_rename",
                reason=f"Symbol {name_path!r} not found in {file!r}.",
            ).model_dump_json(indent=2)
        # v0.2.0-B: permanent integration of the real Stage 1D
        # MultiServerCoordinator.merge_rename signature
        # ``(relative_file_path, line, column, new_name, language)`` returning
        # ``(workspace_edit_or_none, warnings)``. The Stage 2B adapter shim
        # try/except over a kwarg-shape used by test doubles is gone; doubles
        # now match the real positional signature.
        try:
            rel_path = str(Path(file).relative_to(project_root))
        except ValueError:
            rel_path = file
        merge_out = _run_async(coord.merge_rename(
            relative_file_path=rel_path,
            line=int(position.get("line", 0)),
            column=int(position.get("character", position.get("column", 0))),
            new_name=new_name,
            language=lang,
        ))
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        workspace_edit, _ = merge_out
        # v0.2.0-E: when renaming a Python symbol, augment the WorkspaceEdit
        # with __all__ updates so ``from module import *`` continues to expose
        # the symbol under its new name. No-op when __all__ is absent or does
        # not contain the old name.
        if lang == "python" and workspace_edit is not None:
            old_segment = name_path.split("::")[-1].split(".")[-1]
            workspace_edit = _augment_workspace_edit_with_all_update(
                workspace_edit=workspace_edit,
                file=file, old_name=old_segment, new_name=new_name,
            )
        merged_dict = {
            "workspace_edit": workspace_edit or {},
            "primary_server": "pylsp-rope" if lang == "python" else "rust-analyzer",
        }
        if dry_run:
            return RefactorResult(
                applied=False, no_op=False,
                diagnostics_delta=_empty_diagnostics_delta(),
                preview_token=f"pv_rename_{int(time.time())}",
                duration_ms=elapsed_ms,
            ).model_dump_json(indent=2)
        cid = record_checkpoint_for_workspace_edit(
            workspace_edit=merged_dict.get("workspace_edit", {}), snapshot={},
        )
        return RefactorResult(
            applied=True,
            diagnostics_delta=_empty_diagnostics_delta(),
            checkpoint_id=cid,
            duration_ms=elapsed_ms,
            lsp_ops=(LspOpStat(
                method="textDocument/rename",
                server=str(merged_dict.get("primary_server", "unknown")),
                count=1,
                total_ms=elapsed_ms,
            ),),
        ).model_dump_json(indent=2)

    def _resolve_symbol_position(
        self, *, coord: Any, file: str, name_path: str,
    ) -> dict[str, int] | None:
        """Resolve name_path to an LSP position via the coordinator.

        v0.2.0-C: ``MultiServerCoordinator.find_symbol_position`` is now a
        first-class method backed by ``request_document_symbols`` plus a
        ``request_workspace_symbol`` fallback. The Stage 2A text-search
        fallback (``_text_search_position``) was removed alongside this
        change — every coordinator (real and test-double) is expected to
        expose ``find_symbol_position``.
        """
        return _run_async(coord.find_symbol_position(
            file=file, name_path=name_path,
        ))

    def _rename_python_module(
        self,
        *,
        file: str,
        new_name: str,
        project_root: Path,
        dry_run: bool,
    ) -> RefactorResult:
        rel = str(Path(file).relative_to(project_root))
        target_rel = f"{new_name}.py"
        bridge = _build_python_rope_bridge(project_root)
        try:
            edit = bridge.move_module(rel, target_rel)
        finally:
            try:
                bridge.close()
            except Exception:
                pass
        if dry_run:
            return RefactorResult(
                applied=False, no_op=False,
                diagnostics_delta=_empty_diagnostics_delta(),
                preview_token=f"pv_rename_mod_{int(time.time())}",
            )
        cid = record_checkpoint_for_workspace_edit(edit, snapshot={})
        return RefactorResult(
            applied=True,
            diagnostics_delta=_empty_diagnostics_delta(),
            checkpoint_id=cid,
            lsp_ops=(LspOpStat(
                method="rope.refactor.move",
                server="pylsp-rope",
                count=1, total_ms=0,
            ),),
        )


def _augment_workspace_edit_with_all_update(
    workspace_edit: dict[str, Any],
    file: str,
    old_name: str,
    new_name: str,
) -> dict[str, Any]:
    """Append __all__ updates to a Python rename WorkspaceEdit.

    Backlog #6 (v0.2.0). When ``old_name`` appears as a string literal in the
    file's top-level ``__all__`` list/tuple, append a TextEdit replacing it
    with ``new_name`` so ``from module import *`` continues to expose the
    renamed symbol. No-op when:
      - the file has no top-level ``__all__`` assignment, OR
      - ``__all__`` does not contain ``old_name``, OR
      - the file cannot be read or parsed as Python.

    Mutates and returns ``workspace_edit`` for chaining; only the
    ``changes`` shape is touched today (pylsp-rope's primary form).
    """
    import ast as _ast
    try:
        source = Path(file).read_text(encoding="utf-8")
    except OSError:
        return workspace_edit
    try:
        tree = _ast.parse(source)
    except SyntaxError:
        return workspace_edit
    file_uri = Path(file).as_uri()
    for node in tree.body:
        if not isinstance(node, _ast.Assign):
            continue
        if not any(
            isinstance(t, _ast.Name) and t.id == "__all__"
            for t in node.targets
        ):
            continue
        if not isinstance(node.value, (_ast.List, _ast.Tuple)):
            continue
        for elt in node.value.elts:
            if not (isinstance(elt, _ast.Constant) and elt.value == old_name):
                continue
            line = elt.lineno - 1  # AST is 1-indexed; LSP is 0-indexed.
            col_off = elt.col_offset
            end_col = elt.end_col_offset
            if end_col is None:
                continue
            text_edit = {
                "range": {
                    "start": {"line": line, "character": col_off + 1},
                    "end": {"line": line, "character": end_col - 1},
                },
                "newText": new_name,
            }
            changes = workspace_edit.setdefault("changes", {})
            file_edits = changes.setdefault(file_uri, [])
            file_edits.append(text_edit)
    return workspace_edit


# ---------------------------------------------------------------------------
# T7: ScalpelImportsOrganizeTool
# ---------------------------------------------------------------------------


_ENGINE_TO_PROVENANCE: dict[str, str] = {
    "ruff": "ruff",
    "rope": "pylsp-rope",
    "basedpyright": "basedpyright",
}


class ScalpelImportsOrganizeTool(Tool):
    """Add missing, remove unused, reorder imports across files."""

    def apply(
        self,
        files: list[str],
        add_missing: bool = True,
        remove_unused: bool = True,
        reorder: bool = True,
        engine: Literal["auto", "rope", "ruff", "basedpyright"] = "auto",
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Add missing, remove unused, reorder imports across files.
        Idempotent; safe to re-call.

        :param files: list of source files to organize.
        :param add_missing: synthesize import statements for unresolved names.
        :param remove_unused: drop unused imports.
        :param reorder: sort imports per the engine's house style.
        :param engine: 'auto' (priority table) | 'rope' | 'ruff' | 'basedpyright'.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del add_missing, remove_unused, reorder, preview_token
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        if not files:
            # Q4 boundary check is irrelevant when there are no files; emit no-op.
            return RefactorResult(
                applied=False, no_op=True,
                diagnostics_delta=_empty_diagnostics_delta(),
            ).model_dump_json(indent=2)
        for f in files:
            guard = workspace_boundary_guard(
                file=f, project_root=project_root,
                allow_out_of_workspace=allow_out_of_workspace,
            )
            if guard is not None:
                return guard.model_dump_json(indent=2)
        lang = _infer_language(files[0], language)
        if lang not in ("rust", "python"):
            return build_failure_result(
                code=ErrorCode.INVALID_ARGUMENT,
                stage="scalpel_imports_organize",
                reason=f"Cannot infer language from {files[0]!r}; pass language=.",
                recoverable=False,
            ).model_dump_json(indent=2)
        coord = coordinator_for_facade(language=lang, project_root=project_root)
        t0 = time.monotonic()
        all_actions: list[Any] = []
        for f in files:
            actions = _run_async(coord.merge_code_actions(
                file=f,
                start={"line": 0, "character": 0},
                end={"line": 0, "character": 0},
                only=["source.organizeImports"],
            ))
            all_actions.extend(actions)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if not all_actions:
            return RefactorResult(
                applied=False, no_op=True,
                diagnostics_delta=_empty_diagnostics_delta(),
                duration_ms=elapsed_ms,
            ).model_dump_json(indent=2)
        warnings: list[str] = []
        if engine != "auto":
            keep_provenance = _ENGINE_TO_PROVENANCE.get(engine)
            kept: list[Any] = []
            for a in all_actions:
                if a.provenance == keep_provenance:
                    kept.append(a)
                else:
                    warnings.append(
                        f"engine={engine!r} discards action from {a.provenance!r}",
                    )
            all_actions = kept
        if dry_run:
            return RefactorResult(
                applied=False, no_op=False,
                diagnostics_delta=_empty_diagnostics_delta(),
                preview_token=f"pv_org_{int(time.time())}",
                duration_ms=elapsed_ms,
                warnings=tuple(warnings),
            ).model_dump_json(indent=2)
        # v0.3.0 facade-application: apply every action's resolved edit
        # (multi-file imports_organize touches every file passed in).
        merged_changes: dict[str, list[dict[str, Any]]] = {}
        for a in all_actions:
            edit = _resolve_winner_edit(coord, a)
            if not (isinstance(edit, dict) and edit):
                continue
            _apply_workspace_edit_to_disk(edit)
            for uri, hunks in (edit.get("changes") or {}).items():
                merged_changes.setdefault(uri, []).extend(hunks or [])
        cid_edit = {"changes": merged_changes} if merged_changes else {"changes": {}}
        cid = record_checkpoint_for_workspace_edit(
            workspace_edit=cid_edit, snapshot={},
        )
        return RefactorResult(
            applied=True,
            diagnostics_delta=_empty_diagnostics_delta(),
            checkpoint_id=cid,
            duration_ms=elapsed_ms,
            warnings=tuple(warnings),
            lsp_ops=(LspOpStat(
                method="textDocument/codeAction",
                server="multi",
                count=len(all_actions),
                total_ms=elapsed_ms,
            ),),
        ).model_dump_json(indent=2)


# ---------------------------------------------------------------------------
# T8: ScalpelTransactionCommitTool — 13th always-on tool
# ---------------------------------------------------------------------------


def _strip_txn_prefix(txn_id: str) -> str:
    return txn_id[len("txn_"):] if txn_id.startswith("txn_") else txn_id


def _build_failure_step(
    *, code: ErrorCode, stage: str, reason: str,
) -> RefactorResult:
    failure = build_failure_result(code=code, stage=stage, reason=reason).failure
    return RefactorResult(
        applied=False, no_op=False,
        diagnostics_delta=_empty_diagnostics_delta(),
        failure=failure,
    )


# ---------------------------------------------------------------------------
# Stage 3 (v0.2.0) — Rust ergonomic facades wave A
# ---------------------------------------------------------------------------


def _dispatch_single_kind_facade(
    *,
    stage_name: str,
    file: str,
    position: dict[str, int],
    kind: str,
    project_root: Path,
    dry_run: bool,
    language: Literal["rust", "python"] | None,
    server_label: str = "rust-analyzer",
) -> str:
    """Shared dispatcher for Stage 3 facades that select a single code-action
    kind at a cursor ``position``.

    Caller is expected to have already invoked ``workspace_boundary_guard``
    and short-circuited on rejection (each Tool subclass does so directly so
    the safety call stays visible in ``inspect.getsource(cls.apply)``).
    """
    lang = _infer_language(file, language)
    if lang not in ("rust", "python"):
        return build_failure_result(
            code=ErrorCode.INVALID_ARGUMENT,
            stage=stage_name,
            reason=f"Cannot infer language from {file!r}; pass language=.",
            recoverable=False,
        ).model_dump_json(indent=2)
    coord = coordinator_for_facade(language=lang, project_root=project_root)
    t0 = time.monotonic()
    actions = _run_async(coord.merge_code_actions(
        file=file,
        start=position,
        end=position,
        only=[kind],
    ))
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    if not actions:
        return build_failure_result(
            code=ErrorCode.SYMBOL_NOT_FOUND,
            stage=stage_name,
            reason=f"No {kind} actions surfaced for {file!r}.",
        ).model_dump_json(indent=2)
    if dry_run:
        return RefactorResult(
            applied=False, no_op=False,
            diagnostics_delta=_empty_diagnostics_delta(),
            preview_token=f"pv_{stage_name}_{int(time.time())}",
            duration_ms=elapsed_ms,
        ).model_dump_json(indent=2)
    # v0.3.0 facade-application: pull the resolved WorkspaceEdit for the
    # winner and write it to disk. ``get_action_edit`` returns ``None`` when
    # the action wasn't tracked (synthetic ids in legacy tests, or when
    # resolve failed); in that case fall back to the v0.2.0 empty checkpoint.
    workspace_edit = _resolve_winner_edit(coord, actions[0])
    if isinstance(workspace_edit, dict) and workspace_edit:
        _apply_workspace_edit_to_disk(workspace_edit)
    else:
        workspace_edit = {"changes": {}}
    cid = record_checkpoint_for_workspace_edit(
        workspace_edit=workspace_edit, snapshot={},
    )
    return RefactorResult(
        applied=True,
        diagnostics_delta=_empty_diagnostics_delta(),
        checkpoint_id=cid,
        duration_ms=elapsed_ms,
        lsp_ops=(LspOpStat(
            method="textDocument/codeAction",
            server=server_label,
            count=len(actions),
            total_ms=elapsed_ms,
        ),),
    ).model_dump_json(indent=2)


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


_MODULE_LAYOUT_TO_KIND: dict[str, str] = {
    "file": "refactor.rewrite.move_module_to_file",
    "inline": "refactor.rewrite.move_inline_module_to_file",
}


class ScalpelConvertModuleLayoutTool(Tool):
    """Convert a Rust ``mod foo;`` into ``mod foo {{ ... }}`` (or vice versa)."""

    def apply(
        self,
        file: str,
        position: dict[str, int],
        target_layout: Literal["file", "inline"] = "file",
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Convert a Rust ``mod foo;`` into ``mod foo {{ ... }}`` (or back).

        :param file: source file containing the ``mod`` declaration.
        :param position: LSP cursor on the ``mod`` keyword.
        :param target_layout: 'file' to extract inline module to its own file;
            'inline' to inline a file-backed module.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del preview_token
        kind = _MODULE_LAYOUT_TO_KIND.get(target_layout)
        if kind is None:
            return build_failure_result(
                code=ErrorCode.INVALID_ARGUMENT,
                stage="scalpel_convert_module_layout",
                reason=f"Unknown target_layout {target_layout!r}; expected 'file' or 'inline'.",
                recoverable=False,
            ).model_dump_json(indent=2)
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        guard = workspace_boundary_guard(
            file=file, project_root=project_root,
            allow_out_of_workspace=allow_out_of_workspace,
        )
        if guard is not None:
            return guard.model_dump_json(indent=2)
        return _dispatch_single_kind_facade(
            stage_name="scalpel_convert_module_layout",
            file=file, position=position, kind=kind,
            project_root=project_root,
            dry_run=dry_run, language=language,
        )


_VISIBILITY_KIND = "refactor.rewrite.change_visibility"


class ScalpelChangeVisibilityTool(Tool):
    """Toggle a Rust item's visibility (pub / pub(crate) / pub(super) / private)."""

    def apply(
        self,
        file: str,
        position: dict[str, int],
        target_visibility: Literal["pub", "pub_crate", "pub_super", "private"] = "pub",
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Toggle a Rust item's visibility (pub / pub(crate) / pub(super) / private).

        :param file: source file containing the item.
        :param position: LSP cursor on the item keyword.
        :param target_visibility: requested new visibility tier.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del preview_token, target_visibility
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        guard = workspace_boundary_guard(
            file=file, project_root=project_root,
            allow_out_of_workspace=allow_out_of_workspace,
        )
        if guard is not None:
            return guard.model_dump_json(indent=2)
        return _dispatch_single_kind_facade(
            stage_name="scalpel_change_visibility",
            file=file, position=position, kind=_VISIBILITY_KIND,
            project_root=project_root,
            dry_run=dry_run, language=language,
        )


_TIDY_STRUCTURE_KINDS: tuple[str, ...] = (
    "refactor.rewrite.reorder_impl_items",
    "refactor.rewrite.sort_items",
    "refactor.rewrite.reorder_fields",
)


class ScalpelTidyStructureTool(Tool):
    """Reorder impl items, sort items, and reorder struct fields in a file."""

    def apply(
        self,
        file: str,
        scope: Literal["file", "type", "impl"] = "file",
        position: dict[str, int] | None = None,
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Reorder impl items, sort items, and reorder struct fields. Composite.

        :param file: source file to tidy.
        :param scope: 'file' (whole file), 'type' (a struct/enum at position),
            'impl' (an impl block at position).
        :param position: cursor when scope='type' or 'impl'.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del preview_token, scope
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        guard = workspace_boundary_guard(
            file=file, project_root=project_root,
            allow_out_of_workspace=allow_out_of_workspace,
        )
        if guard is not None:
            return guard.model_dump_json(indent=2)
        lang = _infer_language(file, language)
        if lang not in ("rust", "python"):
            return build_failure_result(
                code=ErrorCode.INVALID_ARGUMENT,
                stage="scalpel_tidy_structure",
                reason=f"Cannot infer language from {file!r}; pass language=.",
                recoverable=False,
            ).model_dump_json(indent=2)
        coord = coordinator_for_facade(language=lang, project_root=project_root)
        cursor = position or {"line": 0, "character": 0}
        t0 = time.monotonic()
        all_actions: list[Any] = []
        for kind in _TIDY_STRUCTURE_KINDS:
            actions = _run_async(coord.merge_code_actions(
                file=file, start=cursor, end=cursor, only=[kind],
            ))
            all_actions.extend(actions)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if not all_actions:
            return RefactorResult(
                applied=False, no_op=True,
                diagnostics_delta=_empty_diagnostics_delta(),
                duration_ms=elapsed_ms,
            ).model_dump_json(indent=2)
        if dry_run:
            return RefactorResult(
                applied=False, no_op=False,
                diagnostics_delta=_empty_diagnostics_delta(),
                preview_token=f"pv_tidy_{int(time.time())}",
                duration_ms=elapsed_ms,
            ).model_dump_json(indent=2)
        # v0.3.0 facade-application: apply every action's resolved edit.
        merged_changes: dict[str, list[dict[str, Any]]] = {}
        for a in all_actions:
            edit = _resolve_winner_edit(coord, a)
            if not (isinstance(edit, dict) and edit):
                continue
            _apply_workspace_edit_to_disk(edit)
            for uri, hunks in (edit.get("changes") or {}).items():
                merged_changes.setdefault(uri, []).extend(hunks or [])
        cid_edit = {"changes": merged_changes} if merged_changes else {"changes": {}}
        cid = record_checkpoint_for_workspace_edit(
            workspace_edit=cid_edit, snapshot={},
        )
        return RefactorResult(
            applied=True,
            diagnostics_delta=_empty_diagnostics_delta(),
            checkpoint_id=cid,
            duration_ms=elapsed_ms,
            lsp_ops=(LspOpStat(
                method="textDocument/codeAction",
                server="rust-analyzer",
                count=len(all_actions),
                total_ms=elapsed_ms,
            ),),
        ).model_dump_json(indent=2)


_TYPE_SHAPE_TO_KIND: dict[str, str] = {
    "named_struct": "refactor.rewrite.convert_tuple_struct_to_named_struct",
    "tuple_struct": "refactor.rewrite.convert_named_struct_to_tuple_struct",
    "iter_for_each_to_for": "refactor.rewrite.convert_iter_for_each_to_for",
    "for_to_iter_for_each": "refactor.rewrite.convert_for_to_iter_for_each",
    "while_to_loop": "refactor.rewrite.convert_while_let_to_loop",
    "match_to_iflet": "refactor.rewrite.replace_match_with_if_let",
    "iflet_to_match": "refactor.rewrite.replace_if_let_with_match",
}


class ScalpelChangeTypeShapeTool(Tool):
    """Apply a Rust ``convert_*_to_*`` rewrite at a cursor."""

    def apply(
        self,
        file: str,
        position: dict[str, int],
        target_shape: str,
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Apply a Rust ``convert_*_to_*`` rewrite at a cursor.

        :param file: source file containing the construct.
        :param position: LSP cursor on the construct.
        :param target_shape: one of 'named_struct', 'tuple_struct',
            'iter_for_each_to_for', 'for_to_iter_for_each', 'while_to_loop',
            'match_to_iflet', 'iflet_to_match'.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del preview_token
        kind = _TYPE_SHAPE_TO_KIND.get(target_shape)
        if kind is None:
            return build_failure_result(
                code=ErrorCode.INVALID_ARGUMENT,
                stage="scalpel_change_type_shape",
                reason=f"Unknown target_shape {target_shape!r}; expected one of {sorted(_TYPE_SHAPE_TO_KIND)}.",
                recoverable=False,
            ).model_dump_json(indent=2)
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        guard = workspace_boundary_guard(
            file=file, project_root=project_root,
            allow_out_of_workspace=allow_out_of_workspace,
        )
        if guard is not None:
            return guard.model_dump_json(indent=2)
        return _dispatch_single_kind_facade(
            stage_name="scalpel_change_type_shape",
            file=file, position=position, kind=kind,
            project_root=project_root,
            dry_run=dry_run, language=language,
        )


# ---------------------------------------------------------------------------
# Stage 3 (v0.2.0) — Rust ergonomic facades wave B
# ---------------------------------------------------------------------------


_RETURN_TYPE_KIND = "refactor.rewrite.change_return_type"


class ScalpelChangeReturnTypeTool(Tool):
    """Rewrite a Rust function's return type at a cursor."""

    def apply(
        self,
        file: str,
        position: dict[str, int],
        new_return_type: str,
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Rewrite a Rust function's return type at a cursor.

        :param file: source file containing the function.
        :param position: LSP cursor on the ``fn`` keyword or return-type token.
        :param new_return_type: replacement type expression (informational —
            rust-analyzer offers a single rewrite per cursor; the target type
            is selected by the assist).
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del preview_token, new_return_type
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        guard = workspace_boundary_guard(
            file=file, project_root=project_root,
            allow_out_of_workspace=allow_out_of_workspace,
        )
        if guard is not None:
            return guard.model_dump_json(indent=2)
        return _dispatch_single_kind_facade(
            stage_name="scalpel_change_return_type",
            file=file, position=position, kind=_RETURN_TYPE_KIND,
            project_root=project_root,
            dry_run=dry_run, language=language,
        )


_MATCH_ARMS_KIND = "quickfix.add_missing_match_arms"


class ScalpelCompleteMatchArmsTool(Tool):
    """Insert the missing arms of a Rust ``match`` over a sealed enum."""

    def apply(
        self,
        file: str,
        position: dict[str, int],
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Insert the missing arms of a Rust ``match`` over a sealed enum.

        :param file: source file containing the match expression.
        :param position: LSP cursor inside the match expression.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del preview_token
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        guard = workspace_boundary_guard(
            file=file, project_root=project_root,
            allow_out_of_workspace=allow_out_of_workspace,
        )
        if guard is not None:
            return guard.model_dump_json(indent=2)
        return _dispatch_single_kind_facade(
            stage_name="scalpel_complete_match_arms",
            file=file, position=position, kind=_MATCH_ARMS_KIND,
            project_root=project_root,
            dry_run=dry_run, language=language,
        )


_LIFETIME_KIND = "refactor.extract.extract_lifetime"


class ScalpelExtractLifetimeTool(Tool):
    """Extract a fresh lifetime parameter for a Rust reference at a cursor."""

    def apply(
        self,
        file: str,
        position: dict[str, int],
        lifetime_name: str = "a",
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Extract a fresh lifetime parameter for a Rust reference at a cursor.

        :param file: source file containing the reference.
        :param position: LSP cursor on the reference token.
        :param lifetime_name: requested name for the new lifetime (without
            leading apostrophe). Informational — rust-analyzer's assist
            picks a non-conflicting name automatically.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del preview_token, lifetime_name
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        guard = workspace_boundary_guard(
            file=file, project_root=project_root,
            allow_out_of_workspace=allow_out_of_workspace,
        )
        if guard is not None:
            return guard.model_dump_json(indent=2)
        return _dispatch_single_kind_facade(
            stage_name="scalpel_extract_lifetime",
            file=file, position=position, kind=_LIFETIME_KIND,
            project_root=project_root,
            dry_run=dry_run, language=language,
        )


_GLOB_IMPORTS_KIND = "refactor.rewrite.expand_glob_imports"


class ScalpelExpandGlobImportsTool(Tool):
    """Expand ``use foo::*;`` into the explicit names it brings into scope."""

    def apply(
        self,
        file: str,
        position: dict[str, int],
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Expand ``use foo::*;`` into the explicit names it brings into scope.

        :param file: source file containing the glob ``use`` statement.
        :param position: LSP cursor on the glob ``*``.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del preview_token
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        guard = workspace_boundary_guard(
            file=file, project_root=project_root,
            allow_out_of_workspace=allow_out_of_workspace,
        )
        if guard is not None:
            return guard.model_dump_json(indent=2)
        return _dispatch_single_kind_facade(
            stage_name="scalpel_expand_glob_imports",
            file=file, position=position, kind=_GLOB_IMPORTS_KIND,
            project_root=project_root,
            dry_run=dry_run, language=language,
        )


# ---------------------------------------------------------------------------
# Stage 3 (v0.2.0) — Rust ergonomic facades wave C
# ---------------------------------------------------------------------------


_GENERATE_TRAIT_IMPL_KIND = "refactor.rewrite.generate_trait_impl"


class ScalpelGenerateTraitImplScaffoldTool(Tool):
    """Generate an ``impl Trait for Type {}`` scaffold at a cursor."""

    def apply(
        self,
        file: str,
        position: dict[str, int],
        trait_name: str,
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Generate an ``impl Trait for Type {}`` scaffold at a cursor.

        :param file: source file containing the type definition.
        :param position: LSP cursor on the type name.
        :param trait_name: trait to scaffold (informational — rust-analyzer's
            assist offers a single trait per cursor).
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del preview_token, trait_name
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        guard = workspace_boundary_guard(
            file=file, project_root=project_root,
            allow_out_of_workspace=allow_out_of_workspace,
        )
        if guard is not None:
            return guard.model_dump_json(indent=2)
        return _dispatch_single_kind_facade(
            stage_name="scalpel_generate_trait_impl_scaffold",
            file=file, position=position, kind=_GENERATE_TRAIT_IMPL_KIND,
            project_root=project_root,
            dry_run=dry_run, language=language,
        )


_MEMBER_KIND_TO_KIND: dict[str, str] = {
    "getter": "refactor.rewrite.generate_getter",
    "setter": "refactor.rewrite.generate_setter",
    "method": "refactor.rewrite.generate_method",
    "default_impl": "refactor.rewrite.generate_default_from_new",
}


class ScalpelGenerateMemberTool(Tool):
    """Generate a getter / setter / method stub for a Rust struct field."""

    def apply(
        self,
        file: str,
        position: dict[str, int],
        member_kind: str,
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Generate a getter / setter / method stub for a Rust struct field.

        :param file: source file containing the field.
        :param position: LSP cursor on the field name.
        :param member_kind: one of 'getter', 'setter', 'method', 'default_impl'.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del preview_token
        kind = _MEMBER_KIND_TO_KIND.get(member_kind)
        if kind is None:
            return build_failure_result(
                code=ErrorCode.INVALID_ARGUMENT,
                stage="scalpel_generate_member",
                reason=f"Unknown member_kind {member_kind!r}; expected one of {sorted(_MEMBER_KIND_TO_KIND)}.",
                recoverable=False,
            ).model_dump_json(indent=2)
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        guard = workspace_boundary_guard(
            file=file, project_root=project_root,
            allow_out_of_workspace=allow_out_of_workspace,
        )
        if guard is not None:
            return guard.model_dump_json(indent=2)
        return _dispatch_single_kind_facade(
            stage_name="scalpel_generate_member",
            file=file, position=position, kind=kind,
            project_root=project_root,
            dry_run=dry_run, language=language,
        )


class ScalpelExpandMacroTool(Tool):
    """Expand a Rust macro at a cursor and return the expanded source."""

    def apply(
        self,
        file: str,
        position: dict[str, int],
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Expand a Rust macro at a cursor and return the expanded source.

        :param file: source file containing the macro invocation.
        :param position: LSP cursor on the macro identifier.
        :param dry_run: preview only (returns the expansion without applying).
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult with the expansion in language_findings.
        """
        del preview_token, dry_run
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        guard = workspace_boundary_guard(
            file=file, project_root=project_root,
            allow_out_of_workspace=allow_out_of_workspace,
        )
        if guard is not None:
            return guard.model_dump_json(indent=2)
        lang = _infer_language(file, language)
        if lang != "rust":
            return build_failure_result(
                code=ErrorCode.INVALID_ARGUMENT,
                stage="scalpel_expand_macro",
                reason="expand_macro is rust-analyzer-only.",
                recoverable=False,
            ).model_dump_json(indent=2)
        coord = coordinator_for_facade(language="rust", project_root=project_root)
        t0 = time.monotonic()
        result = _run_async(coord.expand_macro(file=file, position=position))
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if result is None:
            return RefactorResult(
                applied=False, no_op=True,
                diagnostics_delta=_empty_diagnostics_delta(),
                duration_ms=elapsed_ms,
            ).model_dump_json(indent=2)
        finding = LanguageFinding(
            code="macro_expansion",
            message=f"{result.get('name', '<anonymous>')}: {result.get('expansion', '')}",
        )
        return RefactorResult(
            applied=True,
            diagnostics_delta=_empty_diagnostics_delta(),
            duration_ms=elapsed_ms,
            language_findings=(finding,),
            lsp_ops=(LspOpStat(
                method="rust-analyzer/expandMacro",
                server="rust-analyzer", count=1, total_ms=elapsed_ms,
            ),),
        ).model_dump_json(indent=2)


class ScalpelVerifyAfterRefactorTool(Tool):
    """Composite verification — runnables + relatedTests + flycheck."""

    def apply(
        self,
        file: str,
        position: dict[str, int] | None = None,
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Composite verification — runnables + relatedTests + flycheck.

        :param file: source file (workspace anchor).
        :param position: optional cursor for symbol-scoped runnables.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult with a verify_summary in language_findings.
        """
        del preview_token, dry_run
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        guard = workspace_boundary_guard(
            file=file, project_root=project_root,
            allow_out_of_workspace=allow_out_of_workspace,
        )
        if guard is not None:
            return guard.model_dump_json(indent=2)
        lang = _infer_language(file, language)
        if lang != "rust":
            return build_failure_result(
                code=ErrorCode.INVALID_ARGUMENT,
                stage="scalpel_verify_after_refactor",
                reason="verify_after_refactor is rust-analyzer-only.",
                recoverable=False,
            ).model_dump_json(indent=2)
        coord = coordinator_for_facade(language="rust", project_root=project_root)
        t0 = time.monotonic()
        runnables = _run_async(coord.fetch_runnables(file=file, position=position))
        flycheck = _run_async(coord.run_flycheck(file=file))
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        runnable_count = len(runnables) if runnables else 0
        flycheck_diags = (flycheck or {}).get("diagnostics") or []
        finding = LanguageFinding(
            code="verify_summary",
            message=f"runnables={runnable_count} flycheck_diagnostics={len(flycheck_diags)}",
        )
        return RefactorResult(
            applied=True,
            diagnostics_delta=_empty_diagnostics_delta(),
            duration_ms=elapsed_ms,
            language_findings=(finding,),
            lsp_ops=(
                LspOpStat(method="experimental/runnables", server="rust-analyzer",
                          count=runnable_count, total_ms=elapsed_ms),
                LspOpStat(method="rust-analyzer/runFlycheck", server="rust-analyzer",
                          count=len(flycheck_diags), total_ms=elapsed_ms),
            ),
        ).model_dump_json(indent=2)


# ---------------------------------------------------------------------------
# Stage 3 (v0.2.0) — Python ergonomic facades wave A (pylsp-rope-backed)
# ---------------------------------------------------------------------------


def _python_dispatch_single_kind(
    *,
    stage_name: str,
    file: str,
    position: dict[str, int],
    kind: str,
    project_root: Path,
    dry_run: bool,
    server_label: str = "pylsp-rope",
) -> str:
    """Python-specific shared dispatcher; mirrors ``_dispatch_single_kind_facade``
    but pins ``language='python'`` and labels lsp_ops by the rope/ruff/pyright
    server. Used by Wave A (rope) and Wave B (ruff / basedpyright)."""
    coord = coordinator_for_facade(language="python", project_root=project_root)
    t0 = time.monotonic()
    actions = _run_async(coord.merge_code_actions(
        file=file, start=position, end=position, only=[kind],
    ))
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    if not actions:
        return build_failure_result(
            code=ErrorCode.SYMBOL_NOT_FOUND,
            stage=stage_name,
            reason=f"No {kind} actions surfaced for {file!r}.",
        ).model_dump_json(indent=2)
    if dry_run:
        return RefactorResult(
            applied=False, no_op=False,
            diagnostics_delta=_empty_diagnostics_delta(),
            preview_token=f"pv_{stage_name}_{int(time.time())}",
            duration_ms=elapsed_ms,
        ).model_dump_json(indent=2)
    # v0.3.0 facade-application: same pattern as the Rust dispatcher.
    workspace_edit = _resolve_winner_edit(coord, actions[0])
    if isinstance(workspace_edit, dict) and workspace_edit:
        _apply_workspace_edit_to_disk(workspace_edit)
    else:
        workspace_edit = {"changes": {}}
    cid = record_checkpoint_for_workspace_edit(
        workspace_edit=workspace_edit, snapshot={},
    )
    return RefactorResult(
        applied=True,
        diagnostics_delta=_empty_diagnostics_delta(),
        checkpoint_id=cid,
        duration_ms=elapsed_ms,
        lsp_ops=(LspOpStat(
            method="textDocument/codeAction",
            server=server_label,
            count=len(actions),
            total_ms=elapsed_ms,
        ),),
    ).model_dump_json(indent=2)


_METHOD_OBJECT_KIND = "refactor.rewrite.method_to_method_object"


class ScalpelConvertToMethodObjectTool(Tool):
    """Convert a method body into its own callable object (Rope)."""

    def apply(
        self,
        file: str,
        position: dict[str, int],
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Convert a method body into its own callable object (Rope refactor).

        :param file: Python source file containing the method.
        :param position: LSP cursor inside the method body.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del preview_token, language
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        guard = workspace_boundary_guard(
            file=file, project_root=project_root,
            allow_out_of_workspace=allow_out_of_workspace,
        )
        if guard is not None:
            return guard.model_dump_json(indent=2)
        return _python_dispatch_single_kind(
            stage_name="scalpel_convert_to_method_object",
            file=file, position=position, kind=_METHOD_OBJECT_KIND,
            project_root=project_root, dry_run=dry_run,
        )


_LOCAL_TO_FIELD_KIND = "refactor.rewrite.local_to_field"


class ScalpelLocalToFieldTool(Tool):
    """Promote a local variable to an instance field (Rope refactor)."""

    def apply(
        self,
        file: str,
        position: dict[str, int],
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Promote a local variable to an instance field (Rope refactor).

        :param file: Python source file containing the local.
        :param position: LSP cursor on the local name.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del preview_token, language
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        guard = workspace_boundary_guard(
            file=file, project_root=project_root,
            allow_out_of_workspace=allow_out_of_workspace,
        )
        if guard is not None:
            return guard.model_dump_json(indent=2)
        return _python_dispatch_single_kind(
            stage_name="scalpel_local_to_field",
            file=file, position=position, kind=_LOCAL_TO_FIELD_KIND,
            project_root=project_root, dry_run=dry_run,
        )


_USE_FUNCTION_KIND = "refactor.rewrite.use_function"


class ScalpelUseFunctionTool(Tool):
    """Replace inline expressions with calls to an existing function (Rope)."""

    def apply(
        self,
        file: str,
        position: dict[str, int],
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Replace inline expressions with calls to an existing function (Rope).

        :param file: Python source file containing the function.
        :param position: LSP cursor on the function definition.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del preview_token, language
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        guard = workspace_boundary_guard(
            file=file, project_root=project_root,
            allow_out_of_workspace=allow_out_of_workspace,
        )
        if guard is not None:
            return guard.model_dump_json(indent=2)
        return _python_dispatch_single_kind(
            stage_name="scalpel_use_function",
            file=file, position=position, kind=_USE_FUNCTION_KIND,
            project_root=project_root, dry_run=dry_run,
        )


_INTRODUCE_PARAMETER_KIND = "refactor.rewrite.introduce_parameter"


class ScalpelIntroduceParameterTool(Tool):
    """Lift a local expression into a function parameter (Rope refactor)."""

    def apply(
        self,
        file: str,
        position: dict[str, int],
        parameter_name: str = "p",
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Lift a local expression into a function parameter (Rope refactor).

        :param file: Python source file.
        :param position: LSP cursor on the expression.
        :param parameter_name: requested parameter name.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del preview_token, parameter_name, language
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        guard = workspace_boundary_guard(
            file=file, project_root=project_root,
            allow_out_of_workspace=allow_out_of_workspace,
        )
        if guard is not None:
            return guard.model_dump_json(indent=2)
        return _python_dispatch_single_kind(
            stage_name="scalpel_introduce_parameter",
            file=file, position=position, kind=_INTRODUCE_PARAMETER_KIND,
            project_root=project_root, dry_run=dry_run,
        )


# ---------------------------------------------------------------------------
# Stage 3 (v0.2.0) — Python ergonomic facades wave B (multi-source)
# ---------------------------------------------------------------------------


_GENERATE_FROM_UNDEFINED_KIND = "quickfix.generate"


class ScalpelGenerateFromUndefinedTool(Tool):
    """Generate a function/class/variable stub from an undefined name (Rope)."""

    def apply(
        self,
        file: str,
        position: dict[str, int],
        target_kind: Literal["function", "class", "variable"] = "function",
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Generate a function/class/variable stub from an undefined name (Rope).

        :param file: Python source file containing the undefined reference.
        :param position: LSP cursor on the undefined name.
        :param target_kind: kind of stub to generate.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del preview_token, target_kind, language
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        guard = workspace_boundary_guard(
            file=file, project_root=project_root,
            allow_out_of_workspace=allow_out_of_workspace,
        )
        if guard is not None:
            return guard.model_dump_json(indent=2)
        return _python_dispatch_single_kind(
            stage_name="scalpel_generate_from_undefined",
            file=file, position=position, kind=_GENERATE_FROM_UNDEFINED_KIND,
            project_root=project_root, dry_run=dry_run,
        )


_AUTO_IMPORT_KIND = "quickfix.import"


class ScalpelAutoImportSpecializedTool(Tool):
    """Resolve an undefined name to an explicit ``import`` statement."""

    def apply(
        self,
        file: str,
        position: dict[str, int],
        symbol_name: str,
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Resolve an undefined name to an explicit ``import`` statement.

        Multiple candidates may be offered; this facade applies the highest-
        priority candidate (rope's natural ordering). v1.1 will expose a
        candidate-set parameter for caller-driven disambiguation.

        :param file: Python source file containing the undefined name.
        :param position: LSP cursor on the undefined name.
        :param symbol_name: the unresolved name (informational).
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del preview_token, symbol_name, language
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        guard = workspace_boundary_guard(
            file=file, project_root=project_root,
            allow_out_of_workspace=allow_out_of_workspace,
        )
        if guard is not None:
            return guard.model_dump_json(indent=2)
        return _python_dispatch_single_kind(
            stage_name="scalpel_auto_import_specialized",
            file=file, position=position, kind=_AUTO_IMPORT_KIND,
            project_root=project_root, dry_run=dry_run,
        )


_FIX_LINTS_KIND = "source.fixAll.ruff"


class ScalpelFixLintsTool(Tool):
    """Apply ruff's full set of auto-fixable lints (incl. duplicate-import dedup)."""

    def apply(
        self,
        file: str,
        rules: list[str] | None = None,
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Apply ruff's full set of auto-fixable lints. Closes E13-py dedup.

        ``source.fixAll.ruff`` covers I001 (duplicate-import removal) and the
        rest of ruff's auto-fixable rule set. Use ``scalpel_imports_organize``
        for sort-only behaviour without lint application.

        :param file: Python source file.
        :param rules: optional ruff rule allow-list (informational; ruff's
            auto-fix selection is driven by its own config today).
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del preview_token, rules, language
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        guard = workspace_boundary_guard(
            file=file, project_root=project_root,
            allow_out_of_workspace=allow_out_of_workspace,
        )
        if guard is not None:
            return guard.model_dump_json(indent=2)
        coord = coordinator_for_facade(language="python", project_root=project_root)
        t0 = time.monotonic()
        actions = _run_async(coord.merge_code_actions(
            file=file,
            start={"line": 0, "character": 0},
            end={"line": 0, "character": 0},
            only=[_FIX_LINTS_KIND],
        ))
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if not actions:
            return RefactorResult(
                applied=False, no_op=True,
                diagnostics_delta=_empty_diagnostics_delta(),
                duration_ms=elapsed_ms,
            ).model_dump_json(indent=2)
        if dry_run:
            return RefactorResult(
                applied=False, no_op=False,
                diagnostics_delta=_empty_diagnostics_delta(),
                preview_token=f"pv_fix_lints_{int(time.time())}",
                duration_ms=elapsed_ms,
            ).model_dump_json(indent=2)
        # v0.3.0 facade-application: apply the resolved edit (closes E13-py).
        edit = _resolve_winner_edit(coord, actions[0])
        if isinstance(edit, dict) and edit:
            _apply_workspace_edit_to_disk(edit)
        else:
            edit = {"changes": {}}
        cid = record_checkpoint_for_workspace_edit(workspace_edit=edit, snapshot={})
        return RefactorResult(
            applied=True,
            diagnostics_delta=_empty_diagnostics_delta(),
            checkpoint_id=cid,
            duration_ms=elapsed_ms,
            lsp_ops=(LspOpStat(
                method="textDocument/codeAction",
                server="ruff", count=len(actions), total_ms=elapsed_ms,
            ),),
        ).model_dump_json(indent=2)


_IGNORE_DIAGNOSTIC_KIND_BY_TOOL: dict[str, str] = {
    "pyright": "quickfix.pyright_ignore",
    "ruff": "quickfix.ruff_noqa",
}


class ScalpelIgnoreDiagnosticTool(Tool):
    """Insert an inline ignore-comment for a basedpyright or ruff rule."""

    def apply(
        self,
        file: str,
        position: dict[str, int],
        tool_name: str,
        rule: str,
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Insert an inline ignore-comment (``# pyright: ignore[...]`` or ``# noqa``).

        :param file: Python source file.
        :param position: LSP cursor on the diagnostic.
        :param tool_name: 'pyright' for basedpyright, 'ruff' for ruff.
        :param rule: rule identifier to silence.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' or 'python'; inferred from extension when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del preview_token, rule, language
        kind = _IGNORE_DIAGNOSTIC_KIND_BY_TOOL.get(tool_name)
        if kind is None:
            return build_failure_result(
                code=ErrorCode.INVALID_ARGUMENT,
                stage="scalpel_ignore_diagnostic",
                reason=f"Unknown tool_name {tool_name!r}; expected 'pyright' or 'ruff'.",
                recoverable=False,
            ).model_dump_json(indent=2)
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        guard = workspace_boundary_guard(
            file=file, project_root=project_root,
            allow_out_of_workspace=allow_out_of_workspace,
        )
        if guard is not None:
            return guard.model_dump_json(indent=2)
        server_label = "basedpyright" if tool_name == "pyright" else "ruff"
        return _python_dispatch_single_kind(
            stage_name="scalpel_ignore_diagnostic",
            file=file, position=position, kind=kind,
            project_root=project_root, dry_run=dry_run,
            server_label=server_label,
        )


# Dispatch table for commit-time replay. Entries are bound at module load
# from the facade Tool subclasses; tests patch this dict to inject mocks.
_FACADE_DISPATCH: dict[str, Any] = {}


def _bind_facade_dispatch_table() -> None:
    """Populate _FACADE_DISPATCH with bound `apply` methods of the 5 facades.

    NOTE: Tool subclasses inherit ``Tool.__init__(agent: SerenaAgent)`` but
    the Scalpel facades override ``get_project_root`` and never touch
    ``self.agent``. Tests patch _FACADE_DISPATCH wholesale; the real LLM
    path constructs facade Tools through the MCP framework with a real
    agent. The ``cast(Any, None)`` here is the documented seam where the
    facade dispatch and the agent-bound Tool lifecycle meet — see v0.2.0
    backlog item "transaction-commit dispatch passes agent forward".
    """
    none_agent = cast(Any, None)
    _FACADE_DISPATCH["scalpel_split_file"] = lambda **kw: ScalpelSplitFileTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_extract"] = lambda **kw: ScalpelExtractTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_inline"] = lambda **kw: ScalpelInlineTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_rename"] = lambda **kw: ScalpelRenameTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_imports_organize"] = lambda **kw: ScalpelImportsOrganizeTool(none_agent).apply(**kw)
    # Stage 3 (v0.2.0) — Rust ergonomic facades wave A
    _FACADE_DISPATCH["scalpel_convert_module_layout"] = lambda **kw: ScalpelConvertModuleLayoutTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_change_visibility"] = lambda **kw: ScalpelChangeVisibilityTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_tidy_structure"] = lambda **kw: ScalpelTidyStructureTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_change_type_shape"] = lambda **kw: ScalpelChangeTypeShapeTool(none_agent).apply(**kw)
    # Stage 3 (v0.2.0) — Rust ergonomic facades wave B
    _FACADE_DISPATCH["scalpel_change_return_type"] = lambda **kw: ScalpelChangeReturnTypeTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_complete_match_arms"] = lambda **kw: ScalpelCompleteMatchArmsTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_extract_lifetime"] = lambda **kw: ScalpelExtractLifetimeTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_expand_glob_imports"] = lambda **kw: ScalpelExpandGlobImportsTool(none_agent).apply(**kw)
    # Stage 3 (v0.2.0) — Rust ergonomic facades wave C
    _FACADE_DISPATCH["scalpel_generate_trait_impl_scaffold"] = lambda **kw: ScalpelGenerateTraitImplScaffoldTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_generate_member"] = lambda **kw: ScalpelGenerateMemberTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_expand_macro"] = lambda **kw: ScalpelExpandMacroTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_verify_after_refactor"] = lambda **kw: ScalpelVerifyAfterRefactorTool(none_agent).apply(**kw)
    # Stage 3 (v0.2.0) — Python ergonomic facades wave A
    _FACADE_DISPATCH["scalpel_convert_to_method_object"] = lambda **kw: ScalpelConvertToMethodObjectTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_local_to_field"] = lambda **kw: ScalpelLocalToFieldTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_use_function"] = lambda **kw: ScalpelUseFunctionTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_introduce_parameter"] = lambda **kw: ScalpelIntroduceParameterTool(none_agent).apply(**kw)
    # Stage 3 (v0.2.0) — Python ergonomic facades wave B
    _FACADE_DISPATCH["scalpel_generate_from_undefined"] = lambda **kw: ScalpelGenerateFromUndefinedTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_auto_import_specialized"] = lambda **kw: ScalpelAutoImportSpecializedTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_fix_lints"] = lambda **kw: ScalpelFixLintsTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_ignore_diagnostic"] = lambda **kw: ScalpelIgnoreDiagnosticTool(none_agent).apply(**kw)


class ScalpelTransactionCommitTool(Tool):
    """Commit a previewed transaction from dry_run_compose."""

    def apply(self, transaction_id: str) -> str:
        """Commit a previewed transaction from dry_run_compose. Applies all
        steps atomically, captures one checkpoint per step. Idempotent.

        :param transaction_id: id returned by scalpel_dry_run_compose
            (e.g. 'txn_…').
        :return: JSON TransactionResult.
        """
        from serena.tools.scalpel_schemas import TransactionResult
        runtime = ScalpelRuntime.instance()
        txn_store = runtime.transaction_store()
        raw_id = _strip_txn_prefix(transaction_id)
        steps = txn_store.steps(raw_id)
        if not steps:
            failed = _build_failure_step(
                code=ErrorCode.INVALID_ARGUMENT,
                stage="scalpel_transaction_commit",
                reason=(
                    f"Unknown or empty transaction_id: {transaction_id!r}; "
                    f"call scalpel_dry_run_compose first."
                ),
            )
            return TransactionResult(
                transaction_id=transaction_id,
                per_step=(failed,),
                aggregated_diagnostics_delta=_empty_diagnostics_delta(),
                rolled_back=False,
            ).model_dump_json(indent=2)
        expiry = txn_store.expires_at(raw_id)
        if expiry > 0.0 and expiry < time.time():
            failed = _build_failure_step(
                code=ErrorCode.PREVIEW_EXPIRED,
                stage="scalpel_transaction_commit",
                reason=f"Transaction {transaction_id!r} preview expired at {expiry}.",
            )
            return TransactionResult(
                transaction_id=transaction_id,
                per_step=(failed,),
                aggregated_diagnostics_delta=_empty_diagnostics_delta(),
                rolled_back=False,
            ).model_dump_json(indent=2)
        per_step: list[RefactorResult] = []
        t0 = time.monotonic()
        for idx, step in enumerate(steps):
            tool_name = step.get("tool", "")
            dispatcher = _FACADE_DISPATCH.get(tool_name)
            if dispatcher is None:
                per_step.append(_build_failure_step(
                    code=ErrorCode.CAPABILITY_NOT_AVAILABLE,
                    stage="scalpel_transaction_commit",
                    reason=f"Unknown tool {tool_name!r} in step {idx}.",
                ))
                break
            args = dict(step.get("args", {}))
            args.setdefault("dry_run", False)
            try:
                payload = dispatcher(**args)
            except Exception as exc:  # noqa: BLE001 — surface as failure
                per_step.append(_build_failure_step(
                    code=ErrorCode.INTERNAL_ERROR,
                    stage="scalpel_transaction_commit",
                    reason=f"step {idx} ({tool_name!r}) raised: {exc!r}",
                ))
                break
            try:
                rec = RefactorResult.model_validate_json(payload)
            except Exception as exc:  # noqa: BLE001
                per_step.append(_build_failure_step(
                    code=ErrorCode.INTERNAL_ERROR,
                    stage="scalpel_transaction_commit",
                    reason=f"step {idx} ({tool_name!r}) returned invalid JSON: {exc!r}",
                ))
                break
            per_step.append(rec)
            if rec.checkpoint_id is not None:
                try:
                    txn_store.add_checkpoint(raw_id, rec.checkpoint_id)
                except KeyError:
                    pass
            if not rec.applied:
                # First failing step ends commit (per §5.5 fail-fast contract).
                break
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return TransactionResult(
            transaction_id=transaction_id,
            per_step=tuple(per_step),
            aggregated_diagnostics_delta=_empty_diagnostics_delta(),
            duration_ms=elapsed_ms,
            rolled_back=False,
        ).model_dump_json(indent=2)


_bind_facade_dispatch_table()


__all__ = [
    "ScalpelAutoImportSpecializedTool",
    "ScalpelChangeReturnTypeTool",
    "ScalpelChangeTypeShapeTool",
    "ScalpelChangeVisibilityTool",
    "ScalpelCompleteMatchArmsTool",
    "ScalpelConvertModuleLayoutTool",
    "ScalpelConvertToMethodObjectTool",
    "ScalpelExpandGlobImportsTool",
    "ScalpelExpandMacroTool",
    "ScalpelExtractLifetimeTool",
    "ScalpelExtractTool",
    "ScalpelFixLintsTool",
    "ScalpelGenerateFromUndefinedTool",
    "ScalpelGenerateMemberTool",
    "ScalpelGenerateTraitImplScaffoldTool",
    "ScalpelIgnoreDiagnosticTool",
    "ScalpelImportsOrganizeTool",
    "ScalpelInlineTool",
    "ScalpelIntroduceParameterTool",
    "ScalpelLocalToFieldTool",
    "ScalpelRenameTool",
    "ScalpelSplitFileTool",
    "ScalpelTidyStructureTool",
    "ScalpelTransactionCommitTool",
    "ScalpelUseFunctionTool",
    "ScalpelVerifyAfterRefactorTool",
]


# Apply-source capture — fixes D-debt.md §2 flakes. Function attaches
# __wrapped_source__ to every Scalpel*Tool.apply so introspection is
# independent of linecache. Name-based discovery (DRY): new facades
# auto-register. Callers read via facade_support.get_apply_source(cls).
def _attach_apply_source_to_all_facades() -> None:
    for _name, _obj in list(globals().items()):
        if (
            isinstance(_obj, type)
            and _name.startswith("Scalpel")
            and _name.endswith("Tool")
        ):
            attach_apply_source(_obj)


_attach_apply_source_to_all_facades()
del _attach_apply_source_to_all_facades
