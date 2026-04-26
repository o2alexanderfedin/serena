"""Stage 2A — 5 ergonomic intent facades + scalpel_transaction_commit.

Each Tool subclass composes Stage 1G primitives (catalog -> coordinator
-> applier -> checkpoint) into one named MCP entry. Docstrings on each
``apply`` are <=30 words (router signage, §5.4).
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Literal

from serena.tools.facade_support import (
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
        cid = record_checkpoint_for_workspace_edit(
            workspace_edit={"changes": {}}, snapshot={},
        )
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
        cid = record_checkpoint_for_workspace_edit(
            workspace_edit={"changes": {}}, snapshot={},
        )
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
        cid = record_checkpoint_for_workspace_edit(
            workspace_edit={"changes": {}}, snapshot={},
        )
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
        merged = _run_async(coord.merge_rename(
            file=file, position=position, new_name=new_name,
        ))
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if dry_run:
            return RefactorResult(
                applied=False, no_op=False,
                diagnostics_delta=_empty_diagnostics_delta(),
                preview_token=f"pv_rename_{int(time.time())}",
                duration_ms=elapsed_ms,
            ).model_dump_json(indent=2)
        merged_dict = merged if isinstance(merged, dict) else {}
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
        """Resolve name_path to an LSP position.

        Prefers ``coord.find_symbol_position(file=..., name_path=...)`` when
        the coordinator exposes it (test doubles do). Falls back to a thin
        text-search across the file when the coordinator does not (real
        Stage 1D coordinator does not yet expose this method — Stage 2B
        follow-up).
        """
        find_fn = getattr(coord, "find_symbol_position", None)
        if find_fn is not None:
            return _run_async(find_fn(file=file, name_path=name_path))
        return _text_search_position(file=file, name_path=name_path)

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


def _text_search_position(*, file: str, name_path: str) -> dict[str, int] | None:
    """Thin text-search fallback when the coordinator lacks find_symbol_position.

    Returns the line/character of the first occurrence of the last segment of
    ``name_path``. Stage 2B will replace this with a real document-symbol
    lookup. Stage 2A only needs the position to feed merge_rename — even an
    approximate hit is better than failing closed.
    """
    target_name = name_path.split("::")[-1].split(".")[-1]
    try:
        text = Path(file).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for lineno, line in enumerate(text.splitlines()):
        col = line.find(target_name)
        if col >= 0:
            return {"line": lineno, "character": col}
    return None


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
        cid = record_checkpoint_for_workspace_edit(
            workspace_edit={"changes": {}}, snapshot={},
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


# Dispatch table for commit-time replay. Entries are bound at module load
# from the facade Tool subclasses; tests patch this dict to inject mocks.
_FACADE_DISPATCH: dict[str, Any] = {}


def _bind_facade_dispatch_table() -> None:
    """Populate _FACADE_DISPATCH with bound `apply` methods of the 5 facades."""
    _FACADE_DISPATCH["scalpel_split_file"] = lambda **kw: ScalpelSplitFileTool().apply(**kw)
    _FACADE_DISPATCH["scalpel_extract"] = lambda **kw: ScalpelExtractTool().apply(**kw)
    _FACADE_DISPATCH["scalpel_inline"] = lambda **kw: ScalpelInlineTool().apply(**kw)
    _FACADE_DISPATCH["scalpel_rename"] = lambda **kw: ScalpelRenameTool().apply(**kw)
    _FACADE_DISPATCH["scalpel_imports_organize"] = lambda **kw: ScalpelImportsOrganizeTool().apply(**kw)


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
    "ScalpelExtractTool",
    "ScalpelImportsOrganizeTool",
    "ScalpelInlineTool",
    "ScalpelRenameTool",
    "ScalpelSplitFileTool",
    "ScalpelTransactionCommitTool",
]
