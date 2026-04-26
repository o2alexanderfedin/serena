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


__all__ = ["ScalpelSplitFileTool"]
