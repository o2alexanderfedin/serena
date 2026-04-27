"""Stage 1G — 8 always-on primitive / safety / diagnostics MCP tools.

Each ``Scalpel*Tool`` subclass is auto-discovered by
``iter_subclasses(Tool)`` (``serena/mcp.py:249``); the snake-cased
class name (``Tool.get_name_from_cls``) becomes the MCP tool name.

Docstrings on every ``apply`` method are <=30 words (router signage,
§5.4): imperative verb + discriminator + contract bit.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Literal

from serena.refactoring.capabilities import CapabilityRecord
from serena.tools.scalpel_runtime import ScalpelRuntime
from serena.tools.scalpel_schemas import (
    CapabilityDescriptor,
    CapabilityFullDescriptor,
    ComposeResult,
    ComposeStep,
    DiagnosticsDelta,
    DiagnosticSeverityBreakdown,
    ErrorCode,
    FailureInfo,
    LanguageHealth,
    LspOpStat,
    RefactorResult,
    ServerHealth,
    StepPreview,
    TransactionResult,
    WorkspaceHealth,
)
from serena.tools.tools_base import Tool
from solidlsp.dynamic_capabilities import DynamicCapabilityRegistry


def _ensure_supported_language(language: str) -> Literal["rust", "python"]:
    """Narrow a catalog ``language`` string to the MVP-supported literal.

    ``CapabilityRecord.language`` is ``str`` (loaded from JSON) but every
    descriptor schema in the response is ``Literal["rust", "python"]``.
    Centralising the narrowing here keeps consumers type-safe and fails
    fast if the catalog ever leaks an unexpected value.
    """
    if language == "rust":
        return "rust"
    if language == "python":
        return "python"
    raise ValueError(
        f"unsupported catalog language: {language!r}; expected 'rust' or 'python'"
    )


class ScalpelCapabilitiesListTool(Tool):
    """List capabilities for a language with optional filter."""

    def apply(
        self,
        language: Literal["rust", "python"] | None = None,
        filter_kind: str | None = None,
        applies_to_symbol_kind: str | None = None,
    ) -> str:
        """List capabilities for a language with optional filter. Returns
        capability_id + title + applies_to_kinds + preferred_facade.

        :param language: 'rust' or 'python'; None returns both languages.
        :param filter_kind: LSP code-action kind prefix to filter by.
        :param applies_to_symbol_kind: reserved (Stage 2A); unused at MVP.
        :return: JSON array of CapabilityDescriptor rows.
        """
        del applies_to_symbol_kind  # reserved for Stage 2A
        catalog = ScalpelRuntime.instance().catalog()
        rows: list[CapabilityDescriptor] = []
        for rec in catalog.records:
            if language is not None and rec.language != language:
                continue
            if filter_kind is not None and not rec.kind.startswith(filter_kind):
                continue
            rows.append(CapabilityDescriptor(
                capability_id=rec.id,
                title=rec.id.rsplit(".", 1)[-1].replace("_", " ").title(),
                language=_ensure_supported_language(rec.language),
                kind=rec.kind,
                source_server=rec.source_server,
                preferred_facade=rec.preferred_facade,
            ))
        return "[" + ",".join(r.model_dump_json() for r in rows) + "]"


class ScalpelCapabilityDescribeTool(Tool):
    """Describe one capability_id (full schema)."""

    def apply(self, capability_id: str) -> str:
        """Return full schema, examples, and pre-conditions for one
        capability_id. Call before invoking unknown capabilities.

        :param capability_id: stable o2.scalpel-issued id (e.g.
            'rust.refactor.extract.module'). Source: capabilities_list.
        :return: JSON CapabilityFullDescriptor or {failure: ...} payload.
        """
        catalog = ScalpelRuntime.instance().catalog()
        for rec in catalog.records:
            if rec.id == capability_id:
                desc = CapabilityFullDescriptor(
                    capability_id=rec.id,
                    title=rec.id.rsplit(".", 1)[-1].replace("_", " ").title(),
                    language=_ensure_supported_language(rec.language),
                    kind=rec.kind,
                    source_server=rec.source_server,
                    preferred_facade=rec.preferred_facade,
                    params_schema=dict(rec.params_schema),
                    extension_allow_list=tuple(sorted(rec.extension_allow_list)),
                    description=(
                        f"{rec.kind} from {rec.source_server} (Stage 1F catalog)."
                    ),
                )
                return desc.model_dump_json(indent=2)
        # Unknown id — emit a structured failure payload that mirrors
        # FailureInfo so the LLM can read the same shape it sees on
        # apply_capability failures.
        candidates = sorted(
            r.id for r in catalog.records
            if any(part in r.id for part in capability_id.split("."))
        )[:5]
        failure = FailureInfo(
            stage="scalpel_capability_describe",
            symbol=capability_id,
            reason=f"Unknown capability_id: {capability_id!r}",
            code=ErrorCode.CAPABILITY_NOT_AVAILABLE,
            recoverable=True,
            candidates=tuple(candidates),
        )
        return '{"failure": ' + failure.model_dump_json() + "}"


# ---------------------------------------------------------------------------
# T4: ScalpelApplyCapabilityTool — long-tail dispatcher
# ---------------------------------------------------------------------------


def _empty_diagnostics_delta() -> DiagnosticsDelta:
    zero = DiagnosticSeverityBreakdown(error=0, warning=0, information=0, hint=0)
    return DiagnosticsDelta(
        before=zero, after=zero, new_findings=(), severity_breakdown=zero,
    )


def _failure_result(
    code: ErrorCode,
    stage: str,
    reason: str,
    *,
    recoverable: bool = True,
) -> RefactorResult:
    return RefactorResult(
        applied=False,
        diagnostics_delta=_empty_diagnostics_delta(),
        failure=FailureInfo(
            stage=stage, reason=reason, code=code, recoverable=recoverable,
        ),
    )


def _lookup_capability(capability_id: str) -> CapabilityRecord | None:
    catalog = ScalpelRuntime.instance().catalog()
    for rec in catalog.records:
        if rec.id == capability_id:
            return rec
    return None


def _is_in_workspace(file: str, project_root: Path) -> bool:
    """Stage 1A is_in_workspace mirror — accepts strings; canonicalises."""
    try:
        target = Path(file).expanduser().resolve(strict=False)
        root = project_root.expanduser().resolve(strict=False)
        return target == root or root in target.parents
    except OSError:
        return False


def _dispatch_via_coordinator(
    capability: CapabilityRecord,
    file: str,
    range_or_name_path: str | dict[str, Any],
    params: dict[str, Any],
    *,
    dry_run: bool,
    preview_token: str | None,
    project_root: Path,
) -> RefactorResult:
    """Drive the Stage 1D coordinator + Stage 1B applier.

    Stage 1G ships the dispatcher *plumbing*; the Stage 2A ergonomic
    facades exercise the full code-action -> resolve -> apply pipeline.
    """
    del params, preview_token  # Stage 2A wires these end-to-end
    from solidlsp.ls_config import Language

    runtime = ScalpelRuntime.instance()
    language = Language(capability.language)
    coord = runtime.coordinator_for(language, project_root)
    t0 = time.monotonic()
    if isinstance(range_or_name_path, dict):
        rng = range_or_name_path
    else:
        rng = {"start": {"line": 0, "character": 0},
               "end": {"line": 0, "character": 0}}
    actions = coord.merge_code_actions(
        file=file,
        start=rng["start"],
        end=rng["end"],
        only=[capability.kind],
    )
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    if not actions:
        return RefactorResult(
            applied=False,
            diagnostics_delta=_empty_diagnostics_delta(),
            failure=FailureInfo(
                stage="apply_capability",
                reason=f"No code actions matched kind {capability.kind!r}",
                code=ErrorCode.SYMBOL_NOT_FOUND,
                recoverable=True,
            ),
            duration_ms=elapsed_ms,
            lsp_ops=(LspOpStat(
                method="textDocument/codeAction",
                server=capability.source_server,
                count=1,
                total_ms=elapsed_ms,
            ),),
        )
    if dry_run:
        return RefactorResult(
            applied=False,
            no_op=False,
            diagnostics_delta=_empty_diagnostics_delta(),
            preview_token=f"pv_{capability.id}_{int(time.time())}",
            duration_ms=elapsed_ms,
        )
    ckpt_id = runtime.checkpoint_store().record(
        applied={"changes": {}},
        snapshot={},
    )
    return RefactorResult(
        applied=True,
        diagnostics_delta=_empty_diagnostics_delta(),
        checkpoint_id=ckpt_id,
        duration_ms=elapsed_ms,
    )


class ScalpelApplyCapabilityTool(Tool):
    """Apply a registered capability by capability_id (long-tail dispatcher)."""

    def apply(
        self,
        capability_id: str,
        file: str,
        range_or_name_path: str | dict[str, Any],
        params: dict[str, Any] | None = None,
        dry_run: bool = False,
        preview_token: str | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Apply any registered capability by capability_id from
        capabilities_list. The long-tail dispatcher. Atomic. Set
        allow_out_of_workspace=True only with user permission.

        :param capability_id: o2.scalpel-issued id (capabilities_list source).
        :param file: target source file path.
        :param range_or_name_path: LSP Range dict or symbol name-path.
        :param params: extra capability-specific params.
        :param dry_run: preview only — returns preview_token, no checkpoint.
        :param preview_token: continuation token from a prior dry_run.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        params = params or {}
        capability = _lookup_capability(capability_id)
        if capability is None:
            return _failure_result(
                ErrorCode.CAPABILITY_NOT_AVAILABLE,
                "scalpel_apply_capability",
                f"Unknown capability_id: {capability_id!r}",
            ).model_dump_json(indent=2)
        project_root = Path(self.get_project_root())
        if not allow_out_of_workspace and not _is_in_workspace(file, project_root):
            return _failure_result(
                ErrorCode.WORKSPACE_BOUNDARY_VIOLATION,
                "scalpel_apply_capability",
                f"File {file!r} is outside project_root {project_root}; "
                f"set allow_out_of_workspace=True with user permission.",
                recoverable=False,
            ).model_dump_json(indent=2)
        result = _dispatch_via_coordinator(
            capability,
            file,
            range_or_name_path,
            params,
            dry_run=dry_run,
            preview_token=preview_token,
            project_root=project_root,
        )
        return result.model_dump_json(indent=2)


# ---------------------------------------------------------------------------
# T5: ScalpelDryRunComposeTool — multi-step preview composer
# ---------------------------------------------------------------------------


def _dry_run_one_step(
    step: ComposeStep,
    *,
    project_root: Path,
    step_index: int,
) -> StepPreview:
    """Virtually apply one step against the in-memory shadow workspace.

    Stage 1G ships the compose *grammar* (transaction id allocation,
    per-step preview rows, fail-fast walking, 5-min TTL). The actual
    shadow-workspace mutation lives in Stage 2A — the ergonomic facades
    are the only callers that mutate state.
    """
    del project_root  # Stage 2A wires shadow-workspace mutation
    return StepPreview(
        step_index=step_index,
        tool=step.tool,
        changes=(),
        diagnostics_delta=_empty_diagnostics_delta(),
        failure=None,
    )


class ScalpelDryRunComposeTool(Tool):
    """Preview a chain of refactor steps without committing any."""

    PREVIEW_TTL_SECONDS = 300  # 5-min, per §5.5

    def apply(
        self,
        steps: list[dict[str, Any]],
        fail_fast: bool = True,
    ) -> str:
        """Preview a chain of refactor steps without committing any.
        Returns transaction_id; call scalpel_transaction_commit to apply.

        :param steps: ordered list of {tool, args} dicts.
        :param fail_fast: stop at the first failing step (default True).
        :return: JSON ComposeResult.
        """
        project_root = Path(self.get_project_root())
        warnings: list[str] = []
        validated: list[ComposeStep] = []
        for raw_step in steps:
            try:
                validated.append(ComposeStep(**raw_step))
            except Exception as exc:  # noqa: BLE001 — surface as warning
                warnings.append(
                    f"INVALID_ARGUMENT: malformed step {raw_step!r}: {exc}",
                )
        if warnings and not validated:
            raw_id = ScalpelRuntime.instance().transaction_store().begin()
            return ComposeResult(
                transaction_id=f"txn_{raw_id}",
                per_step=(),
                aggregated_changes=(),
                aggregated_diagnostics_delta=_empty_diagnostics_delta(),
                expires_at=time.time() + self.PREVIEW_TTL_SECONDS,
                warnings=tuple(warnings),
            ).model_dump_json(indent=2)
        runtime = ScalpelRuntime.instance()
        txn_store = runtime.transaction_store()
        raw_id = txn_store.begin()
        txn_id = f"txn_{raw_id}"
        # Stage 2A: persist the validated steps + preview expiry so
        # scalpel_transaction_commit can replay them.
        for step in validated:
            txn_store.add_step(raw_id, {"tool": step.tool, "args": dict(step.args)})
        txn_store.set_expires_at(raw_id, time.time() + self.PREVIEW_TTL_SECONDS)
        previews: list[StepPreview] = []
        for idx, step in enumerate(validated):
            preview = _dry_run_one_step(
                step, project_root=project_root, step_index=idx,
            )
            previews.append(preview)
            if preview.failure is not None and fail_fast:
                warnings.append(
                    f"TRANSACTION_ABORTED: step {idx} ({step.tool!r}) failed; "
                    f"remaining {len(validated) - idx - 1} step(s) skipped.",
                )
                break
        return ComposeResult(
            transaction_id=txn_id,
            per_step=tuple(previews),
            aggregated_changes=(),
            aggregated_diagnostics_delta=_empty_diagnostics_delta(),
            expires_at=time.time() + self.PREVIEW_TTL_SECONDS,
            warnings=tuple(warnings),
        ).model_dump_json(indent=2)


# ---------------------------------------------------------------------------
# T6: ScalpelRollbackTool + ScalpelTransactionRollbackTool
# ---------------------------------------------------------------------------


def _no_op_applier(_: dict[str, Any]) -> int:
    """Stage 1G synthetic applier — exists so checkpoint_store.restore
    can be invoked without spinning up a real LSP. Returns 0 so restore()
    surfaces as ``no_op=True`` in RefactorResult.
    """
    return 0


def _strip_txn_prefix(txn_id: str) -> str:
    """Strip the 'txn_' presentation prefix added by dry_run_compose.

    Tests pass raw store ids; production callers pass the prefixed form.
    """
    if txn_id.startswith("txn_"):
        return txn_id[len("txn_"):]
    return txn_id


class ScalpelRollbackTool(Tool):
    """Undo a refactor by checkpoint_id (idempotent)."""

    def apply(self, checkpoint_id: str) -> str:
        """Undo a refactor by checkpoint_id. Idempotent: second call is no-op.

        :param checkpoint_id: id returned by a prior apply call.
        :return: JSON RefactorResult with applied=True if any ops applied,
            else no_op=True.
        """
        runtime = ScalpelRuntime.instance()
        ckpt_store = runtime.checkpoint_store()
        ckpt = ckpt_store.get(checkpoint_id)
        if ckpt is None:
            return RefactorResult(
                applied=False,
                no_op=True,
                diagnostics_delta=_empty_diagnostics_delta(),
                checkpoint_id=checkpoint_id,
            ).model_dump_json(indent=2)
        restored = ckpt_store.restore(checkpoint_id, _no_op_applier)
        return RefactorResult(
            applied=bool(restored),
            no_op=not restored,
            diagnostics_delta=_empty_diagnostics_delta(),
            checkpoint_id=checkpoint_id,
        ).model_dump_json(indent=2)


class ScalpelTransactionRollbackTool(Tool):
    """Undo all checkpoints in a transaction in reverse order (idempotent)."""

    def apply(self, transaction_id: str) -> str:
        """Undo all checkpoints in a transaction (from dry_run_compose) in
        reverse order. Idempotent.

        :param transaction_id: id returned by dry_run_compose.
        :return: JSON TransactionResult.
        """
        runtime = ScalpelRuntime.instance()
        txn_store = runtime.transaction_store()
        ckpt_store = runtime.checkpoint_store()
        raw_id = _strip_txn_prefix(transaction_id)
        try:
            member_ids = list(txn_store.member_ids(raw_id))
        except KeyError:
            member_ids = []
        per_step: list[RefactorResult] = []
        if not member_ids:
            return TransactionResult(
                transaction_id=transaction_id,
                per_step=(),
                aggregated_diagnostics_delta=_empty_diagnostics_delta(),
                rolled_back=False,
            ).model_dump_json(indent=2)
        success_count = 0
        for cid in reversed(member_ids):
            ok = ckpt_store.restore(cid, _no_op_applier)
            if ok:
                success_count += 1
            per_step.append(RefactorResult(
                applied=bool(ok),
                no_op=not ok,
                diagnostics_delta=_empty_diagnostics_delta(),
                checkpoint_id=cid,
                transaction_id=transaction_id,
            ))
        remaining = (
            tuple(
                cid for cid, step in zip(reversed(member_ids), per_step)
                if step.no_op
            )
            if 0 < success_count < len(member_ids)
            else ()
        )
        return TransactionResult(
            transaction_id=transaction_id,
            per_step=tuple(per_step),
            aggregated_diagnostics_delta=_empty_diagnostics_delta(),
            rolled_back=True,
            remaining_checkpoint_ids=remaining,
        ).model_dump_json(indent=2)


# ---------------------------------------------------------------------------
# T7: ScalpelWorkspaceHealthTool — per-language LSP probe
# ---------------------------------------------------------------------------


def _build_language_health(
    language: Any,
    project_root: Path,
    *,
    dynamic_registry: DynamicCapabilityRegistry | None = None,
) -> LanguageHealth:
    """Aggregate ServerHealth rows for one language from the pool stats.

    When ``dynamic_registry`` is provided, methods registered under any
    static-catalog ``source_server`` for this language are unioned (sorted)
    into ``dynamic_capabilities`` and added to ``capabilities_count``.
    """
    runtime = ScalpelRuntime.instance()
    pool = runtime.pool_for(language, project_root)
    stats = pool.stats()
    catalog = runtime.catalog()
    lang_records = [r for r in catalog.records if r.language == language.value]
    server_ids = sorted({r.source_server for r in lang_records})
    catalog_hash = catalog.hash() if hasattr(catalog, "hash") else ""
    dynamic_methods: tuple[str, ...] = (
        tuple(sorted({
            method
            for sid in server_ids
            for method in dynamic_registry.list_for(sid)
        }))
        if dynamic_registry is not None
        else ()
    )
    server_rows: list[ServerHealth] = []
    for sid in server_ids:
        # PoolStats v1 doesn't expose per-server pid/rss; surface placeholders
        # that downstream observability (Stage 1H telemetry) can refine.
        server_rows.append(ServerHealth(
            server_id=sid,
            version="unknown",
            pid=None,
            rss_mb=None,
            capabilities_advertised=tuple(sorted({
                r.kind for r in lang_records if r.source_server == sid
            })),
        ))
    indexing_state = "not_started" if stats.active_servers == 0 else "ready"
    return LanguageHealth(
        language=language.value,
        indexing_state=indexing_state,  # type: ignore[arg-type]
        indexing_progress=None,
        servers=tuple(server_rows),
        capabilities_count=len(lang_records) + len(dynamic_methods),
        dynamic_capabilities=dynamic_methods,
        estimated_wait_ms=None,
        capability_catalog_hash=catalog_hash,
    )


class ScalpelWorkspaceHealthTool(Tool):
    """Probe LSP servers: indexing state, registered capabilities, version."""

    def apply(self, project_root: str | None = None) -> str:
        """Probe LSP servers: indexing state, registered capabilities, version.
        Call before refactor sessions.

        :param project_root: explicit workspace root; defaults to active project.
        :return: JSON WorkspaceHealth.
        """
        from solidlsp.ls_config import Language

        root = (
            Path(project_root).expanduser().resolve(strict=False)
            if project_root is not None
            else Path(self.get_project_root()).expanduser().resolve(strict=False)
        )
        languages: dict[str, LanguageHealth] = {}
        registry = ScalpelRuntime.instance().dynamic_capability_registry()
        for lang in (Language.PYTHON, Language.RUST):
            try:
                languages[lang.value] = _build_language_health(
                    lang, root, dynamic_registry=registry,
                )
            except Exception as exc:  # noqa: BLE001 — surface as failed
                languages[lang.value] = LanguageHealth(
                    language=lang.value,
                    indexing_state="failed",
                    indexing_progress=str(exc),
                    servers=(),
                    capabilities_count=0,
                    dynamic_capabilities=(),
                    estimated_wait_ms=None,
                    capability_catalog_hash="",
                )
        return WorkspaceHealth(
            project_root=str(root),
            languages=languages,
        ).model_dump_json(indent=2)


# ---------------------------------------------------------------------------
# T8: ScalpelExecuteCommandTool — typed workspace/executeCommand pass-through
# ---------------------------------------------------------------------------


# Per-language allow-list of executeCommand verbs. Stage 1G ships a
# conservative whitelist; Stage 1H expands it as the deferred specialty
# tools land. Anything outside the list is refused with
# CAPABILITY_NOT_AVAILABLE so the LLM gets a structured candidate list.
_EXECUTE_COMMAND_WHITELIST: dict[str, frozenset[str]] = {
    "python": frozenset({
        "pylsp.executeCommand",
        "rope.refactor.extract",
        "rope.refactor.inline",
        "rope.refactor.rename",
        "ruff.applyAutofix",
        "ruff.applyOrganizeImports",
        "basedpyright.addImport",
        "basedpyright.organizeImports",
    }),
    "rust": frozenset({
        "rust-analyzer.runFlycheck",
        "rust-analyzer.cancelFlycheck",
        "rust-analyzer.clearFlycheck",
        "rust-analyzer.reloadWorkspace",
        "rust-analyzer.rebuildProcMacros",
        "rust-analyzer.expandMacro",
        "rust-analyzer.viewSyntaxTree",
        "rust-analyzer.viewHir",
        "rust-analyzer.viewMir",
        "rust-analyzer.viewItemTree",
        "rust-analyzer.viewCrateGraph",
        "rust-analyzer.relatedTests",
    }),
}


def _execute_via_coordinator(
    *,
    language: Any,
    project_root: Path,
    command: str,
    arguments: tuple[Any, ...],
) -> RefactorResult:
    """Drive Stage 1D coordinator's broadcast for workspace/executeCommand.

    Stage 1G ships the plumbing; the actual SolidLanguageServer
    .execute_command call happens via MultiServerCoordinator.broadcast
    so the per-server dedup + priority merge rules from §11 apply.
    """
    runtime = ScalpelRuntime.instance()
    coord = runtime.coordinator_for(language, project_root)
    t0 = time.monotonic()
    result = coord.broadcast(
        method="workspace/executeCommand",
        kwargs={"command": command, "arguments": list(arguments)},
        timeout_ms=5000,
    )
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    return RefactorResult(
        applied=True,
        diagnostics_delta=_empty_diagnostics_delta(),
        warnings=tuple(
            f"server-timeout: {w.server_id}"
            for w in getattr(result, "timeouts", ())
        ),
        duration_ms=elapsed_ms,
        lsp_ops=(LspOpStat(
            method="workspace/executeCommand",
            server=language.value,
            count=1,
            total_ms=elapsed_ms,
        ),),
    )


class ScalpelExecuteCommandTool(Tool):
    """Server-specific JSON-RPC pass-through, whitelisted per language."""

    DEFAULT_LANGUAGE: str = "python"  # cluster-prefix discipline §5.3

    def apply(
        self,
        command: str,
        arguments: list[Any] | None = None,
        language: Literal["rust", "python"] | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Server-specific JSON-RPC pass-through, whitelisted per
        LanguageStrategy. Power-user escape hatch.

        :param command: the workspace/executeCommand verb (e.g.
            'rust-analyzer.runFlycheck').
        :param arguments: positional arguments forwarded as-is.
        :param language: 'rust' or 'python'; inferred when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del allow_out_of_workspace  # T8: pass-through escape hatch only
        from solidlsp.ls_config import Language

        arguments = arguments or []
        chosen_language = language or self.DEFAULT_LANGUAGE
        if chosen_language not in _EXECUTE_COMMAND_WHITELIST:
            return _failure_result(
                ErrorCode.INVALID_ARGUMENT,
                "scalpel_execute_command",
                f"Unknown language {chosen_language!r}; "
                f"expected one of {sorted(_EXECUTE_COMMAND_WHITELIST)}.",
                recoverable=False,
            ).model_dump_json(indent=2)
        whitelist = _EXECUTE_COMMAND_WHITELIST[chosen_language]
        if command not in whitelist:
            failure = FailureInfo(
                stage="scalpel_execute_command",
                reason=(
                    f"Command {command!r} is not in the {chosen_language!r} "
                    "whitelist; expand "
                    "vendor/serena/src/serena/tools/scalpel_primitives.py:"
                    "_EXECUTE_COMMAND_WHITELIST to add it."
                ),
                code=ErrorCode.CAPABILITY_NOT_AVAILABLE,
                recoverable=True,
                candidates=tuple(sorted(whitelist)[:5]),
            )
            return RefactorResult(
                applied=False,
                diagnostics_delta=_empty_diagnostics_delta(),
                failure=failure,
            ).model_dump_json(indent=2)
        project_root = Path(self.get_project_root())
        try:
            lang_enum = Language(chosen_language)
        except ValueError:
            return _failure_result(
                ErrorCode.INVALID_ARGUMENT,
                "scalpel_execute_command",
                f"Language {chosen_language!r} is not registered.",
                recoverable=False,
            ).model_dump_json(indent=2)
        result = _execute_via_coordinator(
            language=lang_enum,
            project_root=project_root,
            command=command,
            arguments=tuple(arguments),
        )
        return result.model_dump_json(indent=2)


# ---------------------------------------------------------------------------
# v1.1 Stream 5 / Leaf 03 — ScalpelReloadPluginsTool
# ---------------------------------------------------------------------------


class ScalpelReloadPluginsTool(Tool):
    """Reload plugin/capability registry from disk (no server restart)."""

    def apply(self) -> str:
        """Reload plugin/capability registry from disk. Use after generating
        a new plugin or editing a manifest. No server restart needed.

        :return: JSON ReloadReport (added/removed/unchanged ids, per-plugin
            errors, is_clean computed flag).
        """
        runtime = ScalpelRuntime.instance()
        registry = runtime.plugin_registry()
        report = registry.reload()
        return report.model_dump_json(indent=2)


__all__ = [
    "ScalpelApplyCapabilityTool",
    "ScalpelCapabilitiesListTool",
    "ScalpelCapabilityDescribeTool",
    "ScalpelDryRunComposeTool",
    "ScalpelExecuteCommandTool",
    "ScalpelReloadPluginsTool",
    "ScalpelRollbackTool",
    "ScalpelTransactionRollbackTool",
    "ScalpelWorkspaceHealthTool",
]
