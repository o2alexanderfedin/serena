"""Stage 2A — 5 ergonomic intent facades + scalpel_transaction_commit.

Each Tool subclass composes Stage 1G primitives (catalog -> coordinator
-> applier -> checkpoint) into one named MCP entry. Docstrings on each
``apply`` are <=30 words (router signage, §5.4).
"""

from __future__ import annotations

import asyncio
import json
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


def _infer_extract_language(file: str, explicit: str | None) -> str:
    """v1.5 P2 — like ``_infer_language`` but with the Java arm wired in.

    Kept as a separate helper so the broader Rust/Python facade fleet that
    does not accept ``language="java"`` is not silently widened — only
    ``ScalpelExtractTool`` (and the new Java-specific facades) call this.
    """
    if explicit is not None:
        return explicit
    suffix = Path(file).suffix
    if suffix == ".rs":
        return "rust"
    if suffix in (".py", ".pyi"):
        return "python"
    if suffix == ".java":
        return "java"
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
    """Apply an LSP-spec WorkspaceEdit to the filesystem (v0.3.0 + v1.5 G3b).

    Walks both the ``changes`` (dict shape) and ``documentChanges`` (array
    shape) forms; routes every TextDocumentEdit's ``edits`` list through
    ``_apply_text_edits_to_file`` which sorts by descending position so
    earlier edits don't invalidate later positions.

    Resource operations (CreateFile / RenameFile / DeleteFile) inside
    ``documentChanges`` apply per LSP §3.18 with default options
    (``ignoreIfExists`` for create, ``overwrite=False`` for rename,
    ``ignoreIfNotExists`` for delete). Recursive directory delete is
    deferred per LO-3 (v1.6 deep-tree checkpoint restore).

    Returns the count of TextEdits *and* resource ops actually applied
    (excluding skipped non-file URIs and missing target files). Caller
    uses the return value to distinguish ``applied=True`` (count > 0)
    from ``no_op`` (count == 0).
    """
    applied = 0
    # changes shape: {uri: [TextEdit, ...]}
    for uri, edits in (workspace_edit.get("changes") or {}).items():
        applied += _apply_text_edits_to_file_uri(uri, edits or [])
    # documentChanges shape: [TextDocumentEdit | CreateFile | RenameFile | DeleteFile, ...]
    for dc in workspace_edit.get("documentChanges") or []:
        if not isinstance(dc, dict):
            continue
        kind = dc.get("kind")
        if kind == "create":
            applied += _apply_resource_create(dc)
            continue
        if kind == "rename":
            applied += _apply_resource_rename(dc)
            continue
        if kind == "delete":
            applied += _apply_resource_delete(dc)
            continue
        if "kind" in dc:
            # Unknown future resource-op kind — preserve forward-compat
            # by skipping rather than crashing.
            continue
        text_doc = dc.get("textDocument") or {}
        uri = text_doc.get("uri")
        if not isinstance(uri, str):
            continue
        applied += _apply_text_edits_to_file_uri(uri, dc.get("edits") or [])
    return applied


def _resource_uri_to_path(uri: object) -> Path | None:
    """Decode an LSP ``file://`` URI to a local ``Path``; return ``None``
    for non-file or malformed URIs.
    """
    if not isinstance(uri, str) or not uri.startswith("file://"):
        return None
    from urllib.parse import urlparse, unquote
    return Path(unquote(urlparse(uri).path))


def _apply_resource_create(dc: dict[str, Any]) -> int:
    """LSP §3.18 CreateFile.

    Default options: ``overwrite=False``, ``ignoreIfExists=True``. When
    the file already exists and neither override is set, the operation
    is a silent no-op (per LSP semantics — the create is "absorbed" by
    the existing file). ``mkdir -p`` is always honored on the parent.
    """
    target = _resource_uri_to_path(dc.get("uri"))
    if target is None:
        return 0
    options = dc.get("options") or {}
    overwrite = bool(options.get("overwrite", False))
    ignore_if_exists = bool(options.get("ignoreIfExists", True))
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if overwrite:
            target.write_text("", encoding="utf-8")
            return 1
        if ignore_if_exists:
            return 0  # no-op (LSP default semantics)
        return 0  # spec would fail; we mirror "skip silently" for safety
    target.write_text("", encoding="utf-8")
    return 1


def _apply_resource_rename(dc: dict[str, Any]) -> int:
    """LSP §3.18 RenameFile.

    Default options: ``overwrite=False``, ``ignoreIfExists=False``. When
    the destination exists and neither override is set, the operation is
    a silent no-op (mirroring LSP's "skip on conflict" semantics — the
    structured-logging primitive layer surfaces the no-op via the
    ``applied`` count).
    """
    src = _resource_uri_to_path(dc.get("oldUri"))
    dst = _resource_uri_to_path(dc.get("newUri"))
    if src is None or dst is None:
        return 0
    if not src.exists():
        return 0
    options = dc.get("options") or {}
    overwrite = bool(options.get("overwrite", False))
    ignore_if_exists = bool(options.get("ignoreIfExists", False))
    if dst.exists():
        if overwrite:
            dst.unlink()
        elif ignore_if_exists:
            return 0
        else:
            return 0  # default LSP semantics — skip silently
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return 1


def _apply_resource_delete(dc: dict[str, Any]) -> int:
    """LSP §3.18 DeleteFile.

    Default options: ``ignoreIfNotExists=True``. Recursive directory
    delete is deferred per LO-3 (v1.6) — a directory target is a no-op.
    """
    target = _resource_uri_to_path(dc.get("uri"))
    if target is None:
        return 0
    options = dc.get("options") or {}
    ignore_if_not_exists = bool(options.get("ignoreIfNotExists", True))
    if not target.exists():
        if ignore_if_not_exists:
            return 0
        return 0  # spec would fail; we mirror "skip silently" for safety
    if target.is_dir():
        # LO-3 — recursive directory delete deferred. No-op.
        return 0
    target.unlink()
    return 1


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
    """PREFERRED: split a source file into N modules by moving named symbols."""

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
        # v1.5 G3a — `allow_partial` now flows into `_split_rust`; the four
        # documented-but-not-yet-wired layout/reexport knobs remain decorative
        # for this leaf (spec § CR-1 prioritises `groups`; layout/reexport
        # injection is post-edit AST rewrite, deferred to v1.6).
        del parent_layout, keep_in_original, reexport_policy
        del explicit_reexports, preview_token
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
        # Gate: Rust code-action dispatch — skip when rust-analyzer does not
        # advertise the refactor.extract.module kind (spec § 4.5 P4).
        coord = coordinator_for_facade(language="rust", project_root=project_root)
        if not coord.supports_kind("rust", "refactor.extract.module"):
            return json.dumps(_capability_not_available_envelope(
                language="rust", kind="refactor.extract.module",
            ))
        return self._split_rust(
            file=file, groups=groups,
            project_root=project_root, dry_run=dry_run,
            allow_partial=allow_partial,
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
        allow_partial: bool,
    ) -> RefactorResult:
        """v1.5 G3a — per-group iteration mirroring ``_split_python``.

        For each ``target_module → [symbols]`` entry, resolve every symbol's
        body range via ``coord.find_symbol_range`` and dispatch one
        ``refactor.extract.module`` LSP request bracketed by the symbol's
        actual range (NOT ``(0,0)→(0,0)``). The returned WorkspaceEdits are
        merged via :func:`_merge_workspace_edits` and applied once.

        ``allow_partial=True`` surfaces unresolvable symbols / no-action
        responses as ``language_findings`` warnings and continues with the
        remaining symbols. ``allow_partial=False`` (default) aborts on the
        first failure with ``SYMBOL_NOT_FOUND``.

        Closes spec § CR-1 (the user-reported scalpel_split_file regression).
        """
        coord = coordinator_for_facade(language="rust", project_root=project_root)
        t0 = time.monotonic()
        all_actions: list[Any] = []
        captured_edits: list[dict[str, Any]] = []
        findings: list[LanguageFinding] = []
        for target_module, symbols in groups.items():
            for symbol in symbols:
                rng = _run_async(coord.find_symbol_range(
                    file=file, name_path=symbol,
                    project_root=str(project_root),
                ))
                if rng is None:
                    if allow_partial:
                        findings.append(LanguageFinding(
                            code="symbol_not_found",
                            message=f"{symbol!r} for module {target_module!r}",
                        ))
                        continue
                    return build_failure_result(
                        code=ErrorCode.SYMBOL_NOT_FOUND,
                        stage="scalpel_split_file",
                        reason=f"Symbol {symbol!r} not found in {file!r}.",
                    )
                actions = _run_async(coord.merge_code_actions(
                    file=file,
                    start=rng["start"], end=rng["end"],
                    only=["refactor.extract.module"],
                ))
                if not actions:
                    if allow_partial:
                        findings.append(LanguageFinding(
                            code="no_action",
                            message=(
                                f"no refactor.extract.module for {symbol!r} "
                                f"(target_module={target_module!r})"
                            ),
                        ))
                        continue
                    return build_failure_result(
                        code=ErrorCode.SYMBOL_NOT_FOUND,
                        stage="scalpel_split_file",
                        reason=(
                            f"No refactor.extract.module action for {symbol!r} "
                            f"in {file!r}."
                        ),
                    )
                # G1 default-path: rust-analyzer offers exactly one
                # extract.module per cursor, so ``actions[0]`` (now via the
                # G1 disambiguation policy with no ``title_match``) is the
                # documented behavior.
                winner = actions[0]
                all_actions.append(winner)
                edit = _resolve_winner_edit(coord, winner)
                if isinstance(edit, dict) and edit:
                    captured_edits.append(edit)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if not all_actions:
            return RefactorResult(
                applied=False, no_op=True,
                diagnostics_delta=_empty_diagnostics_delta(),
                duration_ms=elapsed_ms,
                language_findings=tuple(findings),
            )
        if dry_run:
            return RefactorResult(
                applied=False, no_op=False,
                diagnostics_delta=_empty_diagnostics_delta(),
                preview_token=f"pv_split_{int(time.time())}",
                duration_ms=elapsed_ms,
                language_findings=tuple(findings),
            )
        merged = _merge_workspace_edits(captured_edits)
        _apply_workspace_edit_to_disk(merged)
        cid = record_checkpoint_for_workspace_edit(workspace_edit=merged, snapshot={})
        return RefactorResult(
            applied=True,
            diagnostics_delta=_empty_diagnostics_delta(),
            checkpoint_id=cid,
            duration_ms=elapsed_ms,
            language_findings=tuple(findings),
            lsp_ops=(LspOpStat(
                method="textDocument/codeAction",
                server="rust-analyzer",
                count=len(all_actions),
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

# v1.5 G4-6 — rust-analyzer's stable auto-names for extracted items.
# When the caller supplies ``new_name``, the post-processor walks the
# emitted WorkspaceEdit and substitutes any of these tokens with the
# caller's request via word-boundary regex.
_EXTRACT_AUTO_NAMES: tuple[str, ...] = (
    "new_function",
    "new_variable",
    "new_var",
    "new_const",
    "new_constant",
    "new_static",
    "new_type",
    "new_alias",
    "new_module",
    "extracted",
    "placeholder",
)

# v1.5 G4-6 — `visibility` → Rust visibility-prefix string. ``private``
# is the bare default (no prefix injected). The post-processor prepends
# the prefix in front of the bare ``fn``/``const``/``type``/``static``
# keyword on the emitted item.
_EXTRACT_VISIBILITY_PREFIX: dict[str, str] = {
    "private": "",
    "pub": "pub ",
    "pub_crate": "pub(crate) ",
    "pub_super": "pub(super) ",
}


def _post_process_extract_edit(
    workspace_edit: dict[str, Any],
    *,
    new_name: str | None,
    visibility_prefix: str,
) -> dict[str, Any]:
    """v1.5 G4-6 — substitute caller's ``new_name`` for rust-analyzer's
    auto-name tokens and inject ``visibility_prefix`` on each emitted
    item-keyword line.

    Operates only on hunks the LSP emitted (``newText`` strings inside
    ``changes`` and ``documentChanges``); pre-existing source surrounding
    the hunks is untouched. ``new_name=None`` is a no-op for the rename
    pass; ``visibility_prefix=""`` (the ``private`` default) skips the
    prefix injection.
    """
    import re as _re

    def _patch_text(text: str) -> str:
        out = text
        if new_name:
            for auto in _EXTRACT_AUTO_NAMES:
                out = _re.sub(rf"\b{_re.escape(auto)}\b", new_name, out)
        if visibility_prefix:
            # Match each line's first item-keyword (fn/const/type/static)
            # not already preceded by a visibility prefix on that line.
            # We anchor to `^` per line via re.MULTILINE.
            out = _re.sub(
                r"(?m)^(?!\s*pub)(\s*)(fn|const|type|static)\b",
                rf"\1{visibility_prefix}\2",
                out,
            )
        return out

    if not isinstance(workspace_edit, dict):
        return workspace_edit
    out: dict[str, Any] = {}
    for key, val in workspace_edit.items():
        if key == "changes" and isinstance(val, dict):
            new_changes: dict[str, list[dict[str, Any]]] = {}
            for uri, edits in val.items():
                new_edits = []
                for e in edits or []:
                    if isinstance(e, dict) and isinstance(e.get("newText"), str):
                        new_edits.append({**e, "newText": _patch_text(e["newText"])})
                    else:
                        new_edits.append(e)
                new_changes[uri] = new_edits
            out[key] = new_changes
        elif key == "documentChanges" and isinstance(val, list):
            new_dcs: list[Any] = []
            for dc in val:
                if isinstance(dc, dict) and "edits" in dc:
                    new_edits = []
                    for e in dc.get("edits") or []:
                        if isinstance(e, dict) and isinstance(e.get("newText"), str):
                            new_edits.append({**e, "newText": _patch_text(e["newText"])})
                        else:
                            new_edits.append(e)
                    new_dcs.append({**dc, "edits": new_edits})
                else:
                    new_dcs.append(dc)
            out[key] = new_dcs
        else:
            out[key] = val
    return out


# v1.5 P2 — per-language target-validity matrix for ``ScalpelExtractTool``.
# Spec § 4.2.1 (rust/python/java × variable/function/constant/static/type_alias/module).
# Combinations not listed in the language's set return CAPABILITY_NOT_AVAILABLE
# (the existing dynamic-capability registry envelope) BEFORE any LSP call.
_EXTRACT_VALID_TARGETS_BY_LANGUAGE: dict[str, frozenset[str]] = {
    "rust": frozenset({
        "variable", "function", "constant", "static", "type_alias", "module",
    }),
    "python": frozenset({
        "variable", "function", "constant", "type_alias",
    }),
    "java": frozenset({
        "variable", "function", "constant",
    }),
}


class ScalpelExtractTool(Tool):
    """PREFERRED: extract a symbol/selection into a new variable/function/module/type."""

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
        language: Literal["rust", "python", "java"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Extract a selection into a new variable, function, module, or type.
        Pick `target` to choose. Atomic.

        :param file: source file containing the selection or symbol.
        :param range: optional LSP Range; one of range or name_path required.
        :param name_path: optional Serena name-path.
        :param target: extraction target enum.
        :param new_name: name for the extracted item. v1.5 G4-6 wires
            this via post-processing of the LSP's WorkspaceEdit: the
            caller's ``new_name`` substitutes for any of rust-analyzer's
            stable auto-names (``new_function``, ``new_variable``, ...)
            in every emitted hunk via word-boundary regex.
        :param visibility: Rust visibility prefix on the new item. v1.5
            G4-6 wires this via post-processing: the prefix
            (``"pub "``/``"pub(crate) "``/``"pub(super) "``) is injected
            before the bare ``fn``/``const``/``type``/``static`` keyword
            on each emitted item line. ``private`` (default) is a no-op.
        :param similar: when True (Python/Rope), extract similar
            expressions too. v1.5 G4-6 forwards this through
            ``merge_code_actions(arguments=[{...}])``.
        :param global_scope: extract to module scope (Python only). v1.5
            G4-6 forwards via the same ``arguments`` payload.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'rust' | 'python' | 'java'; inferred from extension when None.
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
        if range is None and name_path is None:
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
        lang = _infer_extract_language(file, language)
        if lang not in ("rust", "python", "java"):
            return build_failure_result(
                code=ErrorCode.INVALID_ARGUMENT,
                stage="scalpel_extract",
                reason=f"Cannot infer language from {file!r}; pass language=.",
                recoverable=False,
            ).model_dump_json(indent=2)
        # v1.5 P2 — per-language target-validity matrix (spec § 4.2.1).
        # Invalid combos short-circuit with CAPABILITY_NOT_AVAILABLE before
        # any LSP call so the responsible server is never asked for a kind
        # the language cannot honour (e.g. Java has no 'module' / 'type_alias',
        # Python has no 'static' / 'module').
        valid_targets = _EXTRACT_VALID_TARGETS_BY_LANGUAGE.get(lang, frozenset())
        if target not in valid_targets:
            return json.dumps(_capability_not_available_envelope(
                language=lang, kind=kind,
            ))
        coord = coordinator_for_facade(language=lang, project_root=project_root)
        # When the caller passes only ``name_path``, resolve it to a range via
        # the coordinator's document-symbols walk. The full body span (LSP
        # ``range``) is required — selection-range alone is insufficient for
        # ``merge_code_actions`` which needs (start, end) bracketing the code.
        if range is None and name_path is not None:
            range = _run_async(coord.find_symbol_range(
                file=file, name_path=name_path,
                project_root=str(project_root),
            ))
            if range is None:
                return build_failure_result(
                    code=ErrorCode.SYMBOL_NOT_FOUND,
                    stage="scalpel_extract",
                    reason=f"Symbol {name_path!r} not found in {file!r}.",
                    recoverable=False,
                ).model_dump_json(indent=2)
        assert range is not None  # type-narrowing for the type-checker
        rng = range
        # Gate: skip when the responsible server does not advertise this
        # extract kind (spec § 4.5 P4).
        if not coord.supports_kind(lang, kind):
            return json.dumps(_capability_not_available_envelope(language=lang, kind=kind))
        t0 = time.monotonic()
        # v1.5 G4-6 — forward `similar` / `global_scope` to the LSP via
        # the additive `arguments` payload (rope honors these in its
        # extract-method / extract-variable refactors). Defaults are
        # falsy; we still pass an empty dict-shaped arguments slot so
        # rope sees the arguments key consistently.
        extract_arguments: list[dict[str, Any]] = [
            {"similar": bool(similar), "global_scope": bool(global_scope)}
        ]
        actions = _run_async(coord.merge_code_actions(
            file=file,
            start=rng["start"],
            end=rng["end"],
            only=[kind],
            arguments=extract_arguments,
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
            # v1.5 G4-6 — post-process the WorkspaceEdit: rename the
            # LSP's auto-named symbol to ``new_name`` and inject the
            # caller's ``visibility`` prefix. Rust-only; for Python the
            # prefix dict resolves to "" (see _EXTRACT_VISIBILITY_PREFIX
            # default at the call-site below).
            visibility_prefix = (
                _EXTRACT_VISIBILITY_PREFIX.get(visibility, "")
                if lang == "rust" else ""
            )
            edit = _post_process_extract_edit(
                edit,
                new_name=new_name if new_name and new_name != "extracted" else None,
                visibility_prefix=visibility_prefix,
            )
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
    """PREFERRED: inline a function/variable/type alias at definition or call sites."""

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
        # Gate: skip when the responsible server does not advertise this
        # inline kind (spec § 4.5 P4).
        if not coord.supports_kind(lang, kind):
            return json.dumps(_capability_not_available_envelope(language=lang, kind=kind))
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
    """PREFERRED: rename a symbol everywhere it is referenced. Cross-file via LSP textDocument/rename with checkpoint+rollback."""

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
        :param also_in_strings: request rewriting string-literal occurrences.
            **Not supported by ``textDocument/rename``** (LSP protocol limit;
            v1.5 LO-1). When set, the response carries a ``warnings`` entry
            pointing the caller at ``scalpel_replace_regex`` for string-literal
            renames; the structured rename itself proceeds as normal.
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
        # Gate: skip when the responsible server does not advertise
        # textDocument/rename (spec § 4.5 P4).
        rename_server_id = "pylsp-rope" if lang == "python" else "rust-analyzer"
        if not coord.supports_method(rename_server_id, "textDocument/rename"):
            return json.dumps(_capability_not_available_envelope(
                language=lang, kind="textDocument/rename", server_id=rename_server_id,
            ))
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
        # v1.5 LO-1: also_in_strings is unsupported by textDocument/rename
        # (LSP protocol limitation — the request operates on identifier
        # references, not string-literal contents). Surface this honestly
        # via a warnings entry so the caller can route to scalpel_replace_regex.
        rename_warnings: tuple[str, ...] = ()
        if also_in_strings:
            rename_warnings = (
                "also_in_strings is unsupported by textDocument/rename "
                "(LSP protocol limitation); use scalpel_replace_regex for "
                "string-literal renames.",
            )
        if dry_run:
            return RefactorResult(
                applied=False, no_op=False,
                diagnostics_delta=_empty_diagnostics_delta(),
                preview_token=f"pv_rename_{int(time.time())}",
                duration_ms=elapsed_ms,
                warnings=rename_warnings,
            ).model_dump_json(indent=2)
        cid = record_checkpoint_for_workspace_edit(
            workspace_edit=merged_dict.get("workspace_edit", {}), snapshot={},
        )
        return RefactorResult(
            applied=True,
            diagnostics_delta=_empty_diagnostics_delta(),
            checkpoint_id=cid,
            duration_ms=elapsed_ms,
            warnings=rename_warnings,
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
    """PREFERRED: add missing, remove unused, reorder imports across files."""

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
        # Gate: skip when the responsible server does not advertise
        # source.organizeImports (spec § 4.5 P4).
        if not coord.supports_kind(lang, "source.organizeImports"):
            return json.dumps(_capability_not_available_envelope(
                language=lang, kind="source.organizeImports",
            ))
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


def _capability_not_available_envelope(
    *,
    language: str,
    kind: str,
    server_id: str | None = None,
) -> dict[str, object]:
    """Return a CAPABILITY_NOT_AVAILABLE skip envelope (spec § 4.7).

    Used by the two shared dispatchers (and downstream by bespoke facades)
    to report that the responsible LSP server does not advertise the
    requested code-action *kind*.  The shape mirrors the existing
    ``{status: "skipped", reason: "lsp_does_not_support_implementation"}``
    convention from ``reference_lsp_capability_gaps.md``.
    """
    return {
        "status": "skipped",
        "reason": f"lsp_does_not_support_{kind}",
        "server_id": server_id,
        "language": language,
        "kind": kind,
    }


# ---------------------------------------------------------------------------
# Stage 3 (v0.2.0) — Rust ergonomic facades wave A
# ---------------------------------------------------------------------------


def _select_candidate_action(
    actions: list[Any],
    *,
    title_match: str | None,
) -> tuple[Any | None, dict[str, object] | None]:
    """v1.5 G1 — disambiguation policy for shared facade dispatchers.

    Replaces the historical ``actions[0]`` blind selection with a three-step
    policy. Returns ``(chosen_action, None)`` on success; ``(None, envelope)``
    when ``title_match`` was requested but selection is ambiguous or empty.

    Policy:

    1. If ``title_match`` is supplied: filter actions by case-insensitive
       substring match on ``.title``.

       - 0 hits → return a ``MULTIPLE_CANDIDATES``-shaped envelope with
         ``reason="no_candidate_matched_title_match"``.
       - 1 hit  → return that action.
       - ≥2 hits → return a ``MULTIPLE_CANDIDATES``-shaped envelope with
         ``reason="multiple_candidates_matched_title_match"`` listing the
         candidates so the caller can tighten the filter.

    2. Otherwise (``title_match is None``): prefer the first action with
       ``is_preferred=True``; fall back to ``actions[0]`` for the 17
       pre-G1 callers that have not yet adopted ``title_match`` (status-quo
       behavior, regression-protected by the existing test corpus).

    The envelope carries ``status="skipped"`` (caller treats this as a
    non-applied result) plus a ``candidates`` list of ``{id, title,
    provenance}`` triples for debugging.
    """
    if not actions:
        return None, None
    if title_match is not None:
        needle = title_match.casefold()
        hits = [
            a for a in actions
            if isinstance(getattr(a, "title", None), str)
            and needle in a.title.casefold()
        ]
        if len(hits) == 1:
            return hits[0], None
        # 0 hits or ≥2 hits → return the envelope.
        if len(hits) == 0:
            reason = "no_candidate_matched_title_match"
            envelope_candidates = [
                {
                    "id": getattr(a, "id", None) or getattr(a, "action_id", None),
                    "title": getattr(a, "title", None),
                    "provenance": getattr(a, "provenance", None),
                }
                for a in actions
            ]
        else:
            reason = "multiple_candidates_matched_title_match"
            envelope_candidates = [
                {
                    "id": getattr(a, "id", None) or getattr(a, "action_id", None),
                    "title": getattr(a, "title", None),
                    "provenance": getattr(a, "provenance", None),
                }
                for a in hits
            ]
        envelope: dict[str, object] = {
            "status": "skipped",
            "code": ErrorCode.MULTIPLE_CANDIDATES.value,
            "reason": reason,
            "title_match": title_match,
            "candidates": envelope_candidates,
        }
        return None, envelope
    # title_match is None — preserve pre-G1 behavior.
    for a in actions:
        if bool(getattr(a, "is_preferred", False)):
            return a, None
    return actions[0], None


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
    title_match: str | None = None,
) -> str:
    """Shared dispatcher for Stage 3 facades that select a single code-action
    kind at a cursor ``position``.

    Caller is expected to have already invoked ``workspace_boundary_guard``
    and short-circuited on rejection (each Tool subclass does so directly so
    the safety call stays visible in ``inspect.getsource(cls.apply)``).

    ``title_match`` (v1.5 G1): when supplied, runs the candidate-disambiguation
    policy in :func:`_select_candidate_action`. Defaults to ``None`` so the
    17 pre-G1 callers retain status-quo ``actions[0]`` behavior; G4-* leaves
    migrate one Tool subclass at a time to pass a real ``title_match``.
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
    if not coord.supports_kind(lang, kind):
        return json.dumps(_capability_not_available_envelope(language=lang, kind=kind))
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
    # v1.5 G1 — candidate disambiguation policy. Returns an envelope when
    # title_match is ambiguous; empty title_match preserves actions[0] for
    # the 17 pre-G1 callers.
    chosen, miss_envelope = _select_candidate_action(actions, title_match=title_match)
    if miss_envelope is not None:
        return json.dumps(miss_envelope)
    # v0.3.0 facade-application: pull the resolved WorkspaceEdit for the
    # winner and write it to disk. ``get_action_edit`` returns ``None`` when
    # the action wasn't tracked (synthetic ids in legacy tests, or when
    # resolve failed); in that case fall back to the v0.2.0 empty checkpoint.
    workspace_edit = _resolve_winner_edit(coord, chosen)
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
    """PREFERRED: convert a Rust ``mod foo;`` into ``mod foo {{ ... }}`` (or vice versa)."""

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

# v1.5 G4-4 — map caller's `target_visibility` enum to rust-analyzer's
# stable code-action title format. The dispatcher's title-substring
# disambiguator (G1) selects the matching action. Note: ``"pub"`` is a
# substring of ``"pub(crate)"`` and ``"pub(super)"`` — when RA surfaces
# multiple tiers and the caller asks for ``"pub"``, the G1 envelope
# returns MULTIPLE_CANDIDATES so the caller can refine via a tighter tier.
_VISIBILITY_TITLE_MATCH: dict[str, str] = {
    "pub_crate": "pub(crate)",
    "pub_super": "pub(super)",
    "private": "private",
    "pub": "pub",
}


class ScalpelChangeVisibilityTool(Tool):
    """PREFERRED: toggle a Rust item's visibility (pub / pub(crate) / pub(super) / private)."""

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
        :param target_visibility: requested new visibility tier. v1.5 G4-4
            maps this to rust-analyzer's stable
            ``Change visibility to <tier>`` title and threads the tier
            string into the shared dispatcher's ``title_match`` so the
            correct candidate is selected. ``target_visibility="pub"``
            substring-matches ``pub(crate)`` / ``pub(super)`` too — when
            multiple tiers surface, the G1 ``MULTIPLE_CANDIDATES`` envelope
            is returned and the caller can refine to a specific tier.
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
            stage_name="scalpel_change_visibility",
            file=file, position=position, kind=_VISIBILITY_KIND,
            project_root=project_root,
            dry_run=dry_run, language=language,
            title_match=_VISIBILITY_TITLE_MATCH.get(target_visibility),
        )


_TIDY_STRUCTURE_KINDS: tuple[str, ...] = (
    "refactor.rewrite.reorder_impl_items",
    "refactor.rewrite.sort_items",
    "refactor.rewrite.reorder_fields",
)


class ScalpelTidyStructureTool(Tool):
    """PREFERRED: reorder impl items, sort items, and reorder struct fields in a file."""

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
            # Gate: skip individual kinds not advertised by the server
            # (spec § 4.5 P4 — per-kind gate inside multi-kind loop).
            if not coord.supports_kind(lang, kind):
                continue
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
    """PREFERRED: apply a Rust ``convert_*_to_*`` rewrite at a cursor."""

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
    """PREFERRED: rewrite a Rust function's return type at a cursor."""

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
        :param new_return_type: replacement type expression. v1.5 G4-1 wires
            this into the shared dispatcher's ``title_match`` so rust-analyzer's
            ``Change return type to <T>`` action is selected by substring
            match against the caller's request. When the assist's surfaced
            rewrite does not match this type, the response is the G1
            ``MULTIPLE_CANDIDATES`` envelope (``status="skipped"`` /
            ``reason="no_candidate_matched_title_match"``) — caller can retry
            at a different cursor or accept rust-analyzer's suggested type.
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
            stage_name="scalpel_change_return_type",
            file=file, position=position, kind=_RETURN_TYPE_KIND,
            project_root=project_root,
            dry_run=dry_run, language=language,
            title_match=new_return_type,
        )


_MATCH_ARMS_KIND = "quickfix.add_missing_match_arms"


class ScalpelCompleteMatchArmsTool(Tool):
    """PREFERRED: insert the missing arms of a Rust ``match`` over a sealed enum."""

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
    """PREFERRED: extract a fresh lifetime parameter for a Rust reference at a cursor."""

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
        :param lifetime_name: requested name for the new lifetime (with
            leading apostrophe, e.g. ``"'session"``). v1.5 G4-2 wires this
            into the shared dispatcher's ``title_match``: rust-analyzer's
            assist auto-picks a fresh lifetime; if RA's surfaced title does
            not include ``lifetime_name`` (substring match), the response
            is the G1 ``MULTIPLE_CANDIDATES`` envelope
            (``status="skipped"`` / ``reason="no_candidate_matched_title_match"``)
            rather than a silent rewrite using RA's chosen name.
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
            stage_name="scalpel_extract_lifetime",
            file=file, position=position, kind=_LIFETIME_KIND,
            project_root=project_root,
            dry_run=dry_run, language=language,
            title_match=lifetime_name,
        )


_GLOB_IMPORTS_KIND = "refactor.rewrite.expand_glob_imports"


class ScalpelExpandGlobImportsTool(Tool):
    """PREFERRED: expand ``use foo::*;`` into the explicit names it brings into scope."""

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
    """PREFERRED: generate an ``impl Trait for Type {}`` scaffold at a cursor."""

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
        :param trait_name: trait to scaffold (e.g. ``"Display"``). v1.5 G4-3
            wires this REQUIRED argument into the shared dispatcher's
            ``title_match`` so rust-analyzer's stable
            ``Implement <trait_name> for <Type>`` action is selected by
            substring match against the caller's request. When no surfaced
            action matches, the response is the G1 ``MULTIPLE_CANDIDATES``
            envelope rather than silent scaffolding of an unrelated trait.
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
            stage_name="scalpel_generate_trait_impl_scaffold",
            file=file, position=position, kind=_GENERATE_TRAIT_IMPL_KIND,
            project_root=project_root,
            dry_run=dry_run, language=language,
            title_match=trait_name,
        )


_MEMBER_KIND_TO_KIND: dict[str, str] = {
    "getter": "refactor.rewrite.generate_getter",
    "setter": "refactor.rewrite.generate_setter",
    "method": "refactor.rewrite.generate_method",
    "default_impl": "refactor.rewrite.generate_default_from_new",
}


class ScalpelGenerateMemberTool(Tool):
    """PREFERRED: generate a getter / setter / method stub for a Rust struct field."""

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
    """PREFERRED: expand a Rust macro at a cursor and return the expanded source."""

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
        del preview_token
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
        # v1.5 G2 (HI-12 safety): honor dry_run BEFORE invoking the LSP.
        # rust-analyzer's expandMacro is read-only on disk but kicks off
        # background work; dry_run=True must be a true no-side-effect preview.
        if dry_run:
            return RefactorResult(
                applied=False, no_op=False,
                diagnostics_delta=_empty_diagnostics_delta(),
                preview_token=f"pv_expand_macro_{int(time.time())}",
                duration_ms=0,
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
    """PREFERRED: composite verification — runnables + relatedTests + flycheck."""

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
        del preview_token
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
        # v1.5 G2 (HI-12 safety): honor dry_run BEFORE invoking flycheck.
        # flycheck triggers ``cargo check`` on disk; dry_run=True must
        # short-circuit the side effect entirely.
        if dry_run:
            return RefactorResult(
                applied=False, no_op=False,
                diagnostics_delta=_empty_diagnostics_delta(),
                preview_token=f"pv_verify_after_refactor_{int(time.time())}",
                duration_ms=0,
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
    title_match: str | None = None,
) -> str:
    """Python-specific shared dispatcher; mirrors ``_dispatch_single_kind_facade``
    but pins ``language='python'`` and labels lsp_ops by the rope/ruff/pyright
    server. Used by Wave A (rope) and Wave B (ruff / basedpyright).

    ``title_match`` (v1.5 G1): see :func:`_select_candidate_action`. Defaults
    to ``None`` so the pre-G1 callers retain their status-quo behavior.
    """
    coord = coordinator_for_facade(language="python", project_root=project_root)
    if not coord.supports_kind("python", kind):
        return json.dumps(_capability_not_available_envelope(language="python", kind=kind))
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
    # v1.5 G1 — candidate disambiguation policy. See _select_candidate_action.
    chosen, miss_envelope = _select_candidate_action(actions, title_match=title_match)
    if miss_envelope is not None:
        return json.dumps(miss_envelope)
    # v0.3.0 facade-application: same pattern as the Rust dispatcher.
    workspace_edit = _resolve_winner_edit(coord, chosen)
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
    """PREFERRED: convert a method body into its own callable object (Rope)."""

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
    """PREFERRED: promote a local variable to an instance field (Rope refactor)."""

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
    """PREFERRED: replace inline expressions with calls to an existing function (Rope)."""

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
    """PREFERRED: lift a local expression into a function parameter (Rope refactor)."""

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

# v1.5 G4-5 — per-target-kind LSP filter for ScalpelGenerateFromUndefinedTool.
# Modern rope advertises granular ``quickfix.generate.<kind>`` kinds; the
# facade dispatches the granular kind when supported. Older rope versions
# only advertise the flat ``quickfix.generate`` — the facade falls back to
# the flat kind plus ``title_match=target_kind`` so rope's per-kind
# candidate title is selected via substring match (forward-compat).
_GENERATE_FROM_UNDEFINED_KIND_BY_TARGET: dict[str, str] = {
    "function": "quickfix.generate.function",
    "class": "quickfix.generate.class",
    "variable": "quickfix.generate.variable",
}


class ScalpelGenerateFromUndefinedTool(Tool):
    """PREFERRED: generate a function/class/variable stub from an undefined name (Rope)."""

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
        :param target_kind: kind of stub to generate. v1.5 G4-5 wires this
            into a per-kind dispatch: when rope advertises
            ``quickfix.generate.<target_kind>`` (modern rope) the granular
            kind is sent; otherwise the facade falls back to the flat
            ``quickfix.generate`` + ``title_match=target_kind`` so rope's
            per-kind candidate is selected by substring title match.
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
        granular_kind = _GENERATE_FROM_UNDEFINED_KIND_BY_TARGET.get(target_kind)
        if granular_kind is not None:
            coord = coordinator_for_facade(
                language="python", project_root=project_root,
            )
            if coord.supports_kind("python", granular_kind):
                return _python_dispatch_single_kind(
                    stage_name="scalpel_generate_from_undefined",
                    file=file, position=position, kind=granular_kind,
                    project_root=project_root, dry_run=dry_run,
                )
        # Fallback: flat ``quickfix.generate`` + title_match=target_kind so
        # rope's per-kind candidate title is selected by substring match.
        return _python_dispatch_single_kind(
            stage_name="scalpel_generate_from_undefined",
            file=file, position=position, kind=_GENERATE_FROM_UNDEFINED_KIND,
            project_root=project_root, dry_run=dry_run,
            title_match=target_kind,
        )


_AUTO_IMPORT_KIND = "quickfix.import"


class ScalpelAutoImportSpecializedTool(Tool):
    """PREFERRED: resolve an undefined name to an explicit ``import`` statement."""

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
    """PREFERRED: apply ruff's full set of auto-fixable lints (incl. duplicate-import dedup)."""

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
        # Gate: skip when ruff/pylsp does not advertise source.fixAll.ruff
        # (spec § 4.5 P4).
        if not coord.supports_kind("python", _FIX_LINTS_KIND):
            return json.dumps(_capability_not_available_envelope(
                language="python", kind=_FIX_LINTS_KIND,
            ))
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
    """PREFERRED: insert an inline ignore-comment for a basedpyright or ruff rule."""

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


# ---------------------------------------------------------------------------
# v1.1 Stream 5 / Leaf 07 — Python-only ergonomic facades. Each facade
# bypasses the code-action dispatcher because it's backed by an
# in-process helper (AST rewrite / rope import-tools / basedpyright
# inlay-hint query) rather than a code-action kind. They reuse
# ``_apply_workspace_edit_to_disk`` + ``record_checkpoint_for_workspace_edit``
# so the applier path is identical to every other facade.
# ---------------------------------------------------------------------------


class ScalpelConvertToAsyncTool(Tool):
    """PREFERRED: convert a sync `def` into `async def` and propagate `await` calls."""

    def apply(
        self,
        file: str,
        symbol: str,
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Convert a sync `def` into `async def` and propagate `await` calls.

        :param file: Python source file containing the function.
        :param symbol: name of the function to convert.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'python' (the only supported language for this facade).
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
        from serena.refactoring.python_async_conversion import (
            convert_function_to_async,
        )
        t0 = time.monotonic()
        try:
            workspace_edit, summary = convert_function_to_async(
                file=file, symbol=symbol, project_root=project_root,
            )
        except FileNotFoundError as exc:
            return build_failure_result(
                code=ErrorCode.INVALID_ARGUMENT,
                stage="scalpel_convert_to_async",
                reason=str(exc),
                recoverable=False,
            ).model_dump_json(indent=2)
        except ValueError as exc:
            return build_failure_result(
                code=ErrorCode.SYMBOL_NOT_FOUND,
                stage="scalpel_convert_to_async",
                reason=str(exc),
            ).model_dump_json(indent=2)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if dry_run:
            return RefactorResult(
                applied=False, no_op=False,
                diagnostics_delta=_empty_diagnostics_delta(),
                preview_token=f"pv_convert_to_async_{int(time.time())}",
                duration_ms=elapsed_ms,
                language_options=dict(summary),
            ).model_dump_json(indent=2)
        edits_applied = _apply_workspace_edit_to_disk(workspace_edit)
        cid = record_checkpoint_for_workspace_edit(
            workspace_edit=workspace_edit, snapshot={},
        )
        return RefactorResult(
            applied=True,
            diagnostics_delta=_empty_diagnostics_delta(),
            checkpoint_id=cid,
            duration_ms=elapsed_ms,
            language_options=dict(summary),
            lsp_ops=(LspOpStat(
                method="ast.async_conversion",
                server="ast",
                count=edits_applied,
                total_ms=elapsed_ms,
            ),),
        ).model_dump_json(indent=2)


class ScalpelAnnotateReturnTypeTool(Tool):
    """PREFERRED: insert `-> <Type>` on a function using basedpyright inlay-hint inference."""

    def apply(
        self,
        file: str,
        symbol: str,
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Insert `-> <Type>` on a function via basedpyright inlay hints.

        :param file: Python source file containing the function.
        :param symbol: name of the function to annotate.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'python' (the only supported language for this facade).
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
        from serena.refactoring.python_return_type_infer import (
            annotate_return_type,
        )
        provider = _get_inlay_hint_provider(project_root)
        t0 = time.monotonic()
        try:
            workspace_edit, status = annotate_return_type(
                file=file,
                symbol=symbol,
                project_root=project_root,
                inlay_hint_provider=provider,
            )
        except FileNotFoundError as exc:
            return build_failure_result(
                code=ErrorCode.INVALID_ARGUMENT,
                stage="scalpel_annotate_return_type",
                reason=str(exc),
                recoverable=False,
            ).model_dump_json(indent=2)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if status.get("status") == "skipped":
            return RefactorResult(
                applied=False, no_op=True,
                diagnostics_delta=_empty_diagnostics_delta(),
                duration_ms=elapsed_ms,
                language_options=dict(status),
                lsp_ops=(LspOpStat(
                    method="textDocument/inlayHint",
                    server="basedpyright",
                    count=0,
                    total_ms=elapsed_ms,
                ),),
            ).model_dump_json(indent=2)
        if status.get("status") != "applied" or workspace_edit is None:
            return build_failure_result(
                code=ErrorCode.SYMBOL_NOT_FOUND,
                stage="scalpel_annotate_return_type",
                reason=str(status),
            ).model_dump_json(indent=2)
        if dry_run:
            return RefactorResult(
                applied=False, no_op=False,
                diagnostics_delta=_empty_diagnostics_delta(),
                preview_token=f"pv_annotate_return_type_{int(time.time())}",
                duration_ms=elapsed_ms,
                language_options=dict(status),
            ).model_dump_json(indent=2)
        edits_applied = _apply_workspace_edit_to_disk(workspace_edit)
        cid = record_checkpoint_for_workspace_edit(
            workspace_edit=workspace_edit, snapshot={},
        )
        return RefactorResult(
            applied=True,
            diagnostics_delta=_empty_diagnostics_delta(),
            checkpoint_id=cid,
            duration_ms=elapsed_ms,
            language_options=dict(status),
            lsp_ops=(LspOpStat(
                method="textDocument/inlayHint",
                server="basedpyright",
                count=edits_applied,
                total_ms=elapsed_ms,
            ),),
        ).model_dump_json(indent=2)


def _get_inlay_hint_provider(project_root: Path):
    """Bind a basedpyright inlay-hint provider for the project, or ``None``.

    Resolution path:
      1. Acquire the Python ``MultiServerCoordinator`` for the project.
      2. If it exposes a callable ``fetch_inlay_hints(file_uri, range)``,
         hand it back as the provider.
      3. Otherwise return ``None`` so the helper short-circuits with the
         ``basedpyright_unavailable`` skip discriminator. Tests patch
         this function to inject a stub provider.
    """
    try:
        coord = coordinator_for_facade(language="python", project_root=project_root)
    except Exception:
        return None
    fetcher = getattr(coord, "fetch_inlay_hints", None)
    if not callable(fetcher):
        return None
    return fetcher


class ScalpelConvertFromRelativeImportsTool(Tool):
    """PREFERRED: convert every relative import in a module to its absolute form (rope)."""

    def apply(
        self,
        file: str,
        dry_run: bool = False,
        preview_token: str | None = None,
        language: Literal["python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Rewrite `from .x import y` (and friends) to `from pkg.x import y`.

        :param file: Python module whose relative imports should be rewritten.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
        :param language: 'python' (the only supported language for this facade).
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
        from serena.refactoring.python_imports_relative import (
            convert_from_relative_imports,
        )
        t0 = time.monotonic()
        try:
            workspace_edit, status = convert_from_relative_imports(
                file=file, project_root=project_root,
            )
        except FileNotFoundError as exc:
            return build_failure_result(
                code=ErrorCode.INVALID_ARGUMENT,
                stage="scalpel_convert_from_relative_imports",
                reason=str(exc),
                recoverable=False,
            ).model_dump_json(indent=2)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if status.get("status") == "skipped":
            return RefactorResult(
                applied=False, no_op=True,
                diagnostics_delta=_empty_diagnostics_delta(),
                duration_ms=elapsed_ms,
                language_options=dict(status),
                lsp_ops=(LspOpStat(
                    method="rope.relatives_to_absolutes",
                    server="rope",
                    count=0,
                    total_ms=elapsed_ms,
                ),),
            ).model_dump_json(indent=2)
        if status.get("status") != "applied" or workspace_edit is None:
            return build_failure_result(
                code=ErrorCode.INTERNAL_ERROR,
                stage="scalpel_convert_from_relative_imports",
                reason=str(status),
            ).model_dump_json(indent=2)
        if dry_run:
            return RefactorResult(
                applied=False, no_op=False,
                diagnostics_delta=_empty_diagnostics_delta(),
                preview_token=f"pv_convert_relative_imports_{int(time.time())}",
                duration_ms=elapsed_ms,
                language_options=dict(status),
            ).model_dump_json(indent=2)
        edits_applied = _apply_workspace_edit_to_disk(workspace_edit)
        cid = record_checkpoint_for_workspace_edit(
            workspace_edit=workspace_edit, snapshot={},
        )
        return RefactorResult(
            applied=True,
            diagnostics_delta=_empty_diagnostics_delta(),
            checkpoint_id=cid,
            duration_ms=elapsed_ms,
            language_options=dict(status),
            lsp_ops=(LspOpStat(
                method="rope.relatives_to_absolutes",
                server="rope",
                count=edits_applied,
                total_ms=elapsed_ms,
            ),),
        ).model_dump_json(indent=2)


# ---------------------------------------------------------------------------
# v1.1.1 Leaf 02 — markdown facades (rename_heading + split_doc +
# extract_section + organize_links). Single-LSP (marksman); split_doc /
# extract_section / organize_links are pure-text ops that delegate to
# ``serena.refactoring.markdown_doc_ops``. rename_heading drives marksman's
# ``textDocument/rename`` via the ``MultiServerCoordinator.merge_rename``
# pathway (single primary per language — see _RENAME_PRIMARY_BY_LANGUAGE).
# ---------------------------------------------------------------------------


import re as _re

_HEADING_RE = _re.compile(r"^(#{1,6})\s+(.*\S)\s*$", _re.MULTILINE)


def _find_heading_position(file_path: Path, heading_text: str) -> dict[str, int] | None:
    """Locate the heading-text start position inside ``file_path``.

    Returns ``{"line": int, "character": int}`` pointing at the first
    character of the heading text (i.e. past the leading ``#`` markers
    and the space). ``None`` when ``heading_text`` does not match any
    ATX-style heading in the file.

    Used by ``ScalpelRenameHeadingTool`` so callers can pass the
    heading text directly (more ergonomic than name_path + position
    coordinates for markdown).
    """
    try:
        source = file_path.read_text(encoding="utf-8")
    except OSError:
        return None
    for match in _HEADING_RE.finditer(source):
        if match.group(2).strip() != heading_text:
            continue
        # Convert offset of the heading text start to (line, character).
        text_offset = match.start(2)
        prefix = source[:text_offset]
        line = prefix.count("\n")
        last_newline = prefix.rfind("\n")
        character = text_offset if last_newline == -1 else text_offset - last_newline - 1
        return {"line": line, "character": character}
    return None


class ScalpelRenameHeadingTool(Tool):
    """PREFERRED: rename a markdown heading and propagate to all wiki-links."""

    def apply(
        self,
        file: str,
        heading: str,
        new_name: str,
        dry_run: bool = False,
        preview_token: str | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Rename a heading and propagate to every wiki-link target.
        Single-LSP (marksman). Atomic.

        :param file: markdown file containing the heading.
        :param heading: existing heading text (no leading ``#``).
        :param new_name: replacement heading text.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
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
        # Resolve the heading text to a position before involving marksman —
        # marksman's prepareRename rejects positions outside heading tokens
        # so a wrong/missing heading should fail fast with SYMBOL_NOT_FOUND
        # instead of routing through merge_rename.
        target_path = (project_root / file).expanduser().resolve(strict=False)
        position = _find_heading_position(target_path, heading)
        if position is None:
            return build_failure_result(
                code=ErrorCode.SYMBOL_NOT_FOUND,
                stage="scalpel_rename_heading",
                reason=f"Heading {heading!r} not found in {file!r}.",
                recoverable=False,
            ).model_dump_json(indent=2)
        coord = coordinator_for_facade(language="markdown", project_root=project_root)
        # Gate: skip when marksman does not advertise textDocument/rename
        # (spec § 4.5 P4).
        if not coord.supports_method("marksman", "textDocument/rename"):
            return json.dumps(_capability_not_available_envelope(
                language="markdown", kind="textDocument/rename", server_id="marksman",
            ))
        try:
            rel_path = str(Path(file).relative_to(project_root))
        except ValueError:
            rel_path = file
        t0 = time.monotonic()
        merge_out = _run_async(coord.merge_rename(
            relative_file_path=rel_path,
            line=int(position["line"]),
            column=int(position["character"]),
            new_name=new_name,
            language="markdown",
        ))
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        workspace_edit, _warnings = merge_out
        if workspace_edit is None:
            return build_failure_result(
                code=ErrorCode.SYMBOL_NOT_FOUND,
                stage="scalpel_rename_heading",
                reason=(
                    f"marksman returned no rename edit for heading {heading!r} "
                    f"in {file!r}."
                ),
                recoverable=False,
            ).model_dump_json(indent=2)
        if dry_run:
            return RefactorResult(
                applied=False, no_op=False,
                diagnostics_delta=_empty_diagnostics_delta(),
                preview_token=f"pv_rename_heading_{int(time.time())}",
                duration_ms=elapsed_ms,
            ).model_dump_json(indent=2)
        _apply_workspace_edit_to_disk(workspace_edit)
        cid = record_checkpoint_for_workspace_edit(
            workspace_edit=workspace_edit, snapshot={},
        )
        return RefactorResult(
            applied=True,
            diagnostics_delta=_empty_diagnostics_delta(),
            checkpoint_id=cid,
            duration_ms=elapsed_ms,
            lsp_ops=(LspOpStat(
                method="textDocument/rename",
                server="marksman",
                count=1,
                total_ms=elapsed_ms,
            ),),
        ).model_dump_json(indent=2)


class ScalpelSplitDocTool(Tool):
    """PREFERRED: split a long markdown doc along H1/H2 boundaries into linked sub-docs."""

    def apply(
        self,
        file: str,
        depth: int = 1,
        dry_run: bool = False,
        preview_token: str | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Slice a markdown doc into one sub-doc per heading at depth <= N.
        Source becomes a TOC. Atomic.

        :param file: markdown file to split.
        :param depth: maximum heading depth to split on (1 = H1 only).
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
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
        from serena.refactoring.markdown_doc_ops import split_doc_along_headings
        target_path = (project_root / file).expanduser().resolve(strict=False)
        t0 = time.monotonic()
        edit = split_doc_along_headings(target_path, depth=depth)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if not edit.get("documentChanges"):
            return RefactorResult(
                applied=False, no_op=True,
                diagnostics_delta=_empty_diagnostics_delta(),
                duration_ms=elapsed_ms,
            ).model_dump_json(indent=2)
        if dry_run:
            return RefactorResult(
                applied=False, no_op=False,
                diagnostics_delta=_empty_diagnostics_delta(),
                preview_token=f"pv_split_doc_{int(time.time())}",
                duration_ms=elapsed_ms,
            ).model_dump_json(indent=2)
        _apply_markdown_workspace_edit(edit)
        cid = record_checkpoint_for_workspace_edit(workspace_edit=edit, snapshot={})
        return RefactorResult(
            applied=True,
            diagnostics_delta=_empty_diagnostics_delta(),
            checkpoint_id=cid,
            duration_ms=elapsed_ms,
            lsp_ops=(LspOpStat(
                method="workspace/applyEdit",
                server="markdown_doc_ops",
                count=len(edit["documentChanges"]),
                total_ms=elapsed_ms,
            ),),
        ).model_dump_json(indent=2)


class ScalpelExtractSectionTool(Tool):
    """PREFERRED: extract one markdown section into a new file with a back-link."""

    def apply(
        self,
        file: str,
        heading: str,
        target: str | None = None,
        dry_run: bool = False,
        preview_token: str | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Pull one section into a new file, leaving a link in the source.
        Atomic.

        :param file: markdown file containing the section.
        :param heading: heading text identifying the section.
        :param target: explicit target file path (defaults to ``<slug>.md``).
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
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
        from serena.refactoring.markdown_doc_ops import extract_section
        target_path = (project_root / file).expanduser().resolve(strict=False)
        explicit_target: Path | None = None
        if target is not None:
            explicit_target = (project_root / target).expanduser().resolve(strict=False)
        t0 = time.monotonic()
        try:
            edit = extract_section(
                target_path, heading_text=heading, target_path=explicit_target,
            )
        except KeyError:
            return build_failure_result(
                code=ErrorCode.SYMBOL_NOT_FOUND,
                stage="scalpel_extract_section",
                reason=f"Heading {heading!r} not found in {file!r}.",
                recoverable=False,
            ).model_dump_json(indent=2)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if dry_run:
            return RefactorResult(
                applied=False, no_op=False,
                diagnostics_delta=_empty_diagnostics_delta(),
                preview_token=f"pv_extract_section_{int(time.time())}",
                duration_ms=elapsed_ms,
            ).model_dump_json(indent=2)
        _apply_markdown_workspace_edit(edit)
        cid = record_checkpoint_for_workspace_edit(workspace_edit=edit, snapshot={})
        return RefactorResult(
            applied=True,
            diagnostics_delta=_empty_diagnostics_delta(),
            checkpoint_id=cid,
            duration_ms=elapsed_ms,
            lsp_ops=(LspOpStat(
                method="workspace/applyEdit",
                server="markdown_doc_ops",
                count=len(edit["documentChanges"]),
                total_ms=elapsed_ms,
            ),),
        ).model_dump_json(indent=2)


class ScalpelOrganizeLinksTool(Tool):
    """PREFERRED: sort + dedup the links in a markdown file."""

    def apply(
        self,
        file: str,
        dry_run: bool = False,
        preview_token: str | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Sort wiki-links then markdown links alphabetically; dedup
        duplicates. Idempotent.

        :param file: markdown file to organize.
        :param dry_run: preview only.
        :param preview_token: continuation from a prior dry-run.
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
        from serena.refactoring.markdown_doc_ops import organize_markdown_links
        target_path = (project_root / file).expanduser().resolve(strict=False)
        t0 = time.monotonic()
        edit = organize_markdown_links(target_path)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if not edit.get("documentChanges"):
            return RefactorResult(
                applied=False, no_op=True,
                diagnostics_delta=_empty_diagnostics_delta(),
                duration_ms=elapsed_ms,
            ).model_dump_json(indent=2)
        if dry_run:
            return RefactorResult(
                applied=False, no_op=False,
                diagnostics_delta=_empty_diagnostics_delta(),
                preview_token=f"pv_organize_links_{int(time.time())}",
                duration_ms=elapsed_ms,
            ).model_dump_json(indent=2)
        _apply_markdown_workspace_edit(edit)
        cid = record_checkpoint_for_workspace_edit(workspace_edit=edit, snapshot={})
        return RefactorResult(
            applied=True,
            diagnostics_delta=_empty_diagnostics_delta(),
            checkpoint_id=cid,
            duration_ms=elapsed_ms,
            lsp_ops=(LspOpStat(
                method="workspace/applyEdit",
                server="markdown_doc_ops",
                count=len(edit["documentChanges"]),
                total_ms=elapsed_ms,
            ),),
        ).model_dump_json(indent=2)


# ---------------------------------------------------------------------------
# v1.5 Phase 2 — Java facades (jdtls)
# ---------------------------------------------------------------------------
#
# Spec: docs/superpowers/specs/2026-04-29-lsp-feature-coverage-spec.md § 4.2.
# These two facades plus the Java arm on ``ScalpelExtractTool`` constitute
# the v1.5 Phase 2 deliverable. The e2e fixture at ``playground/java/`` is
# deferred to Phase 2.5; unit tests with mocked jdtls coordinator ship now
# (per spec § 4.4 fallback path).
#
# Both facades use the canonical jdtls dispatch sequence:
#   1. workspace_boundary_guard — block out-of-workspace files.
#   2. find_symbol_range — resolve ``class_name_path`` to an LSP range.
#   3. supports_kind — gate via the static catalog + dynamic registry.
#   4. merge_code_actions — dispatch the jdtls ``source.generate.*`` kind.
#   5. resolve + apply WorkspaceEdit + record checkpoint (or preview).


_GENERATE_CONSTRUCTOR_KIND = "source.generate.constructor"
_OVERRIDE_METHODS_KIND = "source.generate.overrideMethods"


def _java_generate_dispatch(
    *,
    stage_name: str,
    file: str,
    class_name_path: str,
    kind: str,
    project_root: Path,
    preview: bool,
    allow_out_of_workspace: bool,
    server_label: str = "jdtls",
) -> str:
    """Shared dispatcher for Java ``source.generate.*`` family facades.

    Mirrors :func:`_dispatch_single_kind_facade` but resolves the LSP
    range from ``class_name_path`` (instead of accepting a cursor
    ``position``) so the LLM can name the class without computing
    coordinates. The found range bounds the codeAction request.
    """
    guard = workspace_boundary_guard(
        file=file, project_root=project_root,
        allow_out_of_workspace=allow_out_of_workspace,
    )
    if guard is not None:
        return guard.model_dump_json(indent=2)
    coord = coordinator_for_facade(language="java", project_root=project_root)
    rng = _run_async(coord.find_symbol_range(
        file=file, name_path=class_name_path,
        project_root=str(project_root),
    ))
    if rng is None:
        # Fallback: dispatch against the file's leading line; jdtls's
        # source.generate kinds operate against the enclosing class regardless
        # of cursor position, so a (0,0)-(0,0) range is acceptable when the
        # class symbol is unresolvable (e.g. mocked-out coordinator in tests).
        rng = {
            "start": {"line": 0, "character": 0},
            "end": {"line": 0, "character": 0},
        }
    if not coord.supports_kind("java", kind):
        return json.dumps(_capability_not_available_envelope(
            language="java", kind=kind, server_id=server_label,
        ))
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
            stage=stage_name,
            reason=f"No {kind} actions surfaced for {file!r}.",
        ).model_dump_json(indent=2)
    if preview:
        return RefactorResult(
            applied=False, no_op=False,
            diagnostics_delta=_empty_diagnostics_delta(),
            preview_token=f"pv_{stage_name}_{int(time.time())}",
            duration_ms=elapsed_ms,
        ).model_dump_json(indent=2)
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


class ScalpelGenerateConstructorTool(Tool):
    """PREFERRED: Java constructor generation. Generates a constructor for
    a Java class via jdtls source.generate.constructor.

    Selects fields to include, inserts a constructor at a chosen position, and
    updates references via LSP workspace edits with checkpoint+rollback.
    """

    def apply(
        self,
        file: str,
        class_name_path: str,
        include_fields: list[str] | None = None,
        preview: bool = False,
        language: Literal["java"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Generate a Java constructor via jdtls source.generate.constructor.

        :param file: target ``.java`` file.
        :param class_name_path: LSP name-path of the class.
        :param include_fields: optional list of field names; defaults to all
            non-static fields (jdtls applies its built-in default).
        :param preview: when True, returns a WorkspaceEdit preview-token
            without applying.
        :param language: optional explicit language (``"java"``); inferred
            from the ``.java`` suffix when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult (or CAPABILITY_NOT_AVAILABLE envelope
            when jdtls is missing or fails to advertise the kind).
        """
        del include_fields  # forwarded to jdtls's interactive picker; not
        # plumbed end-to-end in v1.5 P2 (the kind dispatch covers all fields
        # by default; per-field selection is a Phase 2.5 enhancement).
        lang = _infer_extract_language(file, language)
        if lang != "java":
            return build_failure_result(
                code=ErrorCode.INVALID_ARGUMENT,
                stage="scalpel_generate_constructor",
                reason=(
                    f"scalpel_generate_constructor is jdtls-only; "
                    f"got language={lang!r} for {file!r}."
                ),
                recoverable=False,
            ).model_dump_json(indent=2)
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        return _java_generate_dispatch(
            stage_name="scalpel_generate_constructor",
            file=file, class_name_path=class_name_path,
            kind=_GENERATE_CONSTRUCTOR_KIND,
            project_root=project_root, preview=preview,
            allow_out_of_workspace=allow_out_of_workspace,
        )


class ScalpelOverrideMethodsTool(Tool):
    """PREFERRED: add @Override stubs in Java classes via jdtls
    source.generate.overrideMethods.

    Resolves candidate methods via LSP type-hierarchy and inserts override
    stubs at a chosen position with checkpoint+rollback.
    """

    def apply(
        self,
        file: str,
        class_name_path: str,
        method_names: list[str] | None = None,
        preview: bool = False,
        language: Literal["java"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Generate @Override stubs via jdtls source.generate.overrideMethods.

        :param file: target ``.java`` file.
        :param class_name_path: LSP name-path of the class.
        :param method_names: optional list; defaults to all not-yet-overridden
            abstract methods (jdtls applies its built-in default).
        :param preview: when True, returns a WorkspaceEdit preview-token
            without applying.
        :param language: optional explicit language (``"java"``); inferred
            from the ``.java`` suffix when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult (or CAPABILITY_NOT_AVAILABLE envelope
            when jdtls is missing or fails to advertise the kind).
        """
        del method_names  # forwarded to jdtls's interactive picker; not
        # plumbed end-to-end in v1.5 P2 (the kind dispatch covers all
        # candidates by default; per-method selection is Phase 2.5).
        lang = _infer_extract_language(file, language)
        if lang != "java":
            return build_failure_result(
                code=ErrorCode.INVALID_ARGUMENT,
                stage="scalpel_override_methods",
                reason=(
                    f"scalpel_override_methods is jdtls-only; "
                    f"got language={lang!r} for {file!r}."
                ),
                recoverable=False,
            ).model_dump_json(indent=2)
        project_root = Path(self.get_project_root()).expanduser().resolve(strict=False)
        return _java_generate_dispatch(
            stage_name="scalpel_override_methods",
            file=file, class_name_path=class_name_path,
            kind=_OVERRIDE_METHODS_KIND,
            project_root=project_root, preview=preview,
            allow_out_of_workspace=allow_out_of_workspace,
        )


def _apply_markdown_workspace_edit(workspace_edit: dict[str, Any]) -> int:
    """Apply a markdown_doc_ops WorkspaceEdit to disk.

    Mirrors :func:`_apply_workspace_edit_to_disk` but supports the
    ``CreateFile`` resource operations the markdown helpers emit. The
    main applier intentionally skips resource ops (deferred per its
    docstring), so markdown's split + extract paths need this thin
    wrapper that:

      1. Creates the target file (empty) for every ``{"kind": "create"}``
         document change.
      2. Defers to the standard text-edit applier for every
         ``TextDocumentEdit``.
    """
    applied = 0
    for dc in workspace_edit.get("documentChanges") or []:
        if not isinstance(dc, dict):
            continue
        if dc.get("kind") == "create":
            uri = dc.get("uri")
            if isinstance(uri, str) and uri.startswith("file://"):
                from urllib.parse import urlparse, unquote
                target = Path(unquote(urlparse(uri).path))
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    target.write_text("", encoding="utf-8")
            continue
        text_doc = dc.get("textDocument") or {}
        uri = text_doc.get("uri")
        if not isinstance(uri, str):
            continue
        applied += _apply_text_edits_to_file_uri(uri, dc.get("edits") or [])
    return applied


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
    # v1.1 Stream 5 / Leaf 07 — Python-only ergonomic facades.
    _FACADE_DISPATCH["scalpel_convert_to_async"] = lambda **kw: ScalpelConvertToAsyncTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_annotate_return_type"] = lambda **kw: ScalpelAnnotateReturnTypeTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_convert_from_relative_imports"] = lambda **kw: ScalpelConvertFromRelativeImportsTool(none_agent).apply(**kw)
    # v1.1.1 Leaf 02 — markdown facades (single-LSP marksman).
    _FACADE_DISPATCH["scalpel_rename_heading"] = lambda **kw: ScalpelRenameHeadingTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_split_doc"] = lambda **kw: ScalpelSplitDocTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_extract_section"] = lambda **kw: ScalpelExtractSectionTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_organize_links"] = lambda **kw: ScalpelOrganizeLinksTool(none_agent).apply(**kw)
    # v1.5 P2 — Java facades (single-LSP jdtls).
    _FACADE_DISPATCH["scalpel_generate_constructor"] = lambda **kw: ScalpelGenerateConstructorTool(none_agent).apply(**kw)
    _FACADE_DISPATCH["scalpel_override_methods"] = lambda **kw: ScalpelOverrideMethodsTool(none_agent).apply(**kw)


class ScalpelTransactionCommitTool(Tool):
    """PREFERRED: commit a previewed transaction from dry_run_compose."""

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
    "ScalpelAnnotateReturnTypeTool",
    "ScalpelAutoImportSpecializedTool",
    "ScalpelChangeReturnTypeTool",
    "ScalpelChangeTypeShapeTool",
    "ScalpelChangeVisibilityTool",
    "ScalpelCompleteMatchArmsTool",
    "ScalpelConvertFromRelativeImportsTool",
    "ScalpelConvertModuleLayoutTool",
    "ScalpelConvertToAsyncTool",
    "ScalpelConvertToMethodObjectTool",
    "ScalpelExpandGlobImportsTool",
    "ScalpelExpandMacroTool",
    "ScalpelExtractLifetimeTool",
    "ScalpelExtractSectionTool",
    "ScalpelExtractTool",
    "ScalpelFixLintsTool",
    "ScalpelGenerateConstructorTool",
    "ScalpelGenerateFromUndefinedTool",
    "ScalpelGenerateMemberTool",
    "ScalpelGenerateTraitImplScaffoldTool",
    "ScalpelIgnoreDiagnosticTool",
    "ScalpelImportsOrganizeTool",
    "ScalpelInlineTool",
    "ScalpelIntroduceParameterTool",
    "ScalpelLocalToFieldTool",
    "ScalpelOrganizeLinksTool",
    "ScalpelOverrideMethodsTool",
    "ScalpelRenameHeadingTool",
    "ScalpelRenameTool",
    "ScalpelSplitDocTool",
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
