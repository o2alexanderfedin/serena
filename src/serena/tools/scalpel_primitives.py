"""Stage 1G — 8 always-on primitive / safety / diagnostics MCP tools.

Each ``Scalpel*Tool`` subclass is auto-discovered by
``iter_subclasses(Tool)`` (``serena/mcp.py:249``); the snake-cased
class name (``Tool.get_name_from_cls``) becomes the MCP tool name.

Docstrings on every ``apply`` method are <=30 words (router signage,
§5.4): imperative verb + discriminator + contract bit.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, Literal

from serena.refactoring import STRATEGY_REGISTRY
from serena.refactoring.capabilities import CapabilityRecord
from serena.refactoring.pending_tx import AnnotationGroup, PendingTransaction
from serena.tools.facade_support import (
    _apply_workspace_edit_to_disk,
    apply_action_and_checkpoint,
    inverse_apply_checkpoint,
)
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
    FileChange,
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


def _registered_language_ids() -> frozenset[str]:
    """Return the set of ``language_id`` strings from all registered strategies.

    Using ``strategy_cls.language_id`` (not ``Language`` enum values) because
    catalog records are built from ``strategy_cls.language_id`` — they share
    the same namespace.
    """
    return frozenset(cls.language_id for cls in STRATEGY_REGISTRY.values())


def _ensure_supported_language(language: str) -> str:
    """Validate that *language* has a registered strategy and return it unchanged.

    ``CapabilityRecord.language`` is ``str`` (loaded from JSON).  Rather than
    hardcoding a static ``Literal[...]``, we consult ``STRATEGY_REGISTRY`` so
    that every language added via a plugin is accepted automatically.

    Raises ``ValueError`` with the sorted list of registered language IDs when
    the value has no registered strategy.
    """
    registered = _registered_language_ids()
    if language not in registered:
        raise ValueError(
            f"No strategy registered for language {language!r}; "
            f"registered: {sorted(registered)}"
        )
    return language


class ScalpelCapabilitiesListTool(Tool):
    """PREFERRED: list capabilities for a language with optional filter."""

    def apply(
        self,
        language: str | None = None,
        filter_kind: str | None = None,
        applies_to_symbol_kind: str | None = None,
    ) -> str:
        """List capabilities for a language with optional filter. Returns
        capability_id + title + applies_to_kinds + preferred_facade.

        :param language: language name (e.g. 'rust', 'python', 'typescript',
            'go', 'cpp', 'java', 'lean4', 'smt2', 'prolog', 'problog');
            None returns all languages.
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
    """PREFERRED: describe one capability_id (full schema)."""

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


def _run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    """Drive an async coroutine to completion in a tool's sync ``apply`` path.

    Mirrors ``serena.tools.scalpel_facades._run_async`` (kept local here to
    avoid forming a ``scalpel_primitives -> scalpel_facades`` import edge,
    which v1.6 PR 1 explicitly broke).
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return asyncio.run_coroutine_threadsafe(coro, loop).result()
    except RuntimeError:
        pass
    return asyncio.new_event_loop().run_until_complete(coro)


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

    v1.6 PR 3 (Plan 2): the dispatcher now resolves the winner action's
    ``WorkspaceEdit`` via :func:`apply_action_and_checkpoint` and applies
    it to disk; the v0.2.0 ``applied=True`` lie (recorded an empty
    ``{"changes": {}}`` checkpoint) is gone.

    Note: ``params`` is informational; the LSP server's code-action request
    shapes the dispatch via ``capability.kind`` alone (today's
    ``merge_code_actions(only=[capability.kind])``). Threading ``params``
    into the LSP ``context`` is deferred to a future capability-shape spec.
    ``preview_token`` is reserved for the dry-run continuation contract;
    today's dry-run mints a fresh token rather than threading the prior one.
    """
    del params, preview_token  # see docstring — informational at MVP
    from solidlsp.ls_config import Language

    runtime = ScalpelRuntime.instance()
    language = Language(capability.language)
    coord = runtime.coordinator_for(language, project_root)
    # v1.6 Plan 2 NEW gate — short-circuit when the responsible LSP server
    # does not advertise the capability's code-action kind. Mirrors the
    # named-facade gates (e.g. scalpel_facades.py:195, :428, :2132).
    if not coord.supports_kind(language.value, capability.kind):
        return RefactorResult(
            applied=False,
            diagnostics_delta=_empty_diagnostics_delta(),
            failure=FailureInfo(
                stage="apply_capability",
                reason=(
                    f"Server {capability.source_server!r} does not advertise "
                    f"code-action kind {capability.kind!r} for language "
                    f"{language.value!r}."
                ),
                code=ErrorCode.CAPABILITY_NOT_AVAILABLE,
                recoverable=True,
            ),
        )
    t0 = time.monotonic()
    if isinstance(range_or_name_path, dict):
        rng = range_or_name_path
    else:
        rng = {"start": {"line": 0, "character": 0},
               "end": {"line": 0, "character": 0}}
    actions = _run_async(coord.merge_code_actions(
        file=file,
        start=rng["start"],
        end=rng["end"],
        only=[capability.kind],
    ))
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
    # v1.6 PR 3: resolve the winner action's WorkspaceEdit, snapshot pre-edit
    # bytes, and apply via PR 2's helper. Empty ``cid`` would mean the helper
    # short-circuited without recording — ``apply_action_and_checkpoint``
    # always returns a non-empty id today, but we surface a no-op envelope
    # defensively so the contract stays honest if that invariant ever weakens.
    cid, applied_edit = apply_action_and_checkpoint(coord, actions[0])
    if not cid or applied_edit == {"changes": {}}:
        return RefactorResult(
            applied=False,
            no_op=True,
            diagnostics_delta=_empty_diagnostics_delta(),
            checkpoint_id=cid or None,
            duration_ms=elapsed_ms,
            lsp_ops=(LspOpStat(
                method="textDocument/codeAction",
                server=capability.source_server,
                count=1,
                total_ms=elapsed_ms,
            ),),
        )
    return RefactorResult(
        applied=True,
        diagnostics_delta=_empty_diagnostics_delta(),
        checkpoint_id=cid,
        duration_ms=elapsed_ms,
        lsp_ops=(LspOpStat(
            method="textDocument/codeAction",
            server=capability.source_server,
            count=1,
            total_ms=elapsed_ms,
        ),),
    )


class ScalpelApplyCapabilityTool(Tool):
    """FALLBACK: apply a registered capability by capability_id (long-tail dispatcher).

    This is the safety-valve dispatch path — invoked when no named
    ``scalpel_*`` facade matches the requested kind. Per spec § 5.2.1,
    the ``FALLBACK:`` opener (vs the ``PREFERRED:`` opener used by every
    named facade) is the asymmetric routing signal that lets the LLM
    prefer a specialised tool when one exists.

    Note: params is informational; the LSP server's code-action request
    shapes the dispatch via ``capability_id`` alone (today's
    ``merge_code_actions(only=[capability.kind])``). Threading ``params``
    into the LSP ``context`` is deferred to a future capability-shape spec.
    """

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


def _payload_to_step_changes(
    payload: dict[str, Any],
) -> tuple[FileChange, ...]:
    """Project ``RefactorResult.changes`` from a JSON-decoded payload.

    Returns ``()`` if the field is missing or unparseable. We re-validate
    each change through the pydantic ``FileChange`` model to maintain the
    type guarantee on the ``StepPreview.changes`` field.
    """
    raw = payload.get("changes") or ()
    if not isinstance(raw, (list, tuple)):
        return ()
    out: list[FileChange] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            out.append(FileChange.model_validate(entry))
        except Exception:  # noqa: BLE001 — drop unparseable rows
            continue
    return tuple(out)


def _payload_to_diagnostics_delta(
    payload: dict[str, Any],
) -> DiagnosticsDelta:
    """Project ``RefactorResult.diagnostics_delta`` or fall back to empty."""
    raw = payload.get("diagnostics_delta")
    if isinstance(raw, dict):
        try:
            return DiagnosticsDelta.model_validate(raw)
        except Exception:  # noqa: BLE001 — surface as empty
            pass
    return _empty_diagnostics_delta()


def _payload_to_failure(payload: dict[str, Any]) -> FailureInfo | None:
    """Project ``RefactorResult.failure`` or return ``None``."""
    raw = payload.get("failure")
    if not isinstance(raw, dict):
        return None
    try:
        return FailureInfo.model_validate(raw)
    except Exception:  # noqa: BLE001 — surface as no failure rather than crash
        return None


def _dry_run_one_step(
    step: ComposeStep,
    *,
    project_root: Path,
    step_index: int,
) -> StepPreview:
    """Virtually apply one step by dispatching to its facade in dry_run mode.

    Looks up ``step.tool`` in ``_FACADE_DISPATCH`` (lazy-imported from
    ``scalpel_facades`` — the dispatch table is built at module-init and is
    stable thereafter; lazy import avoids the parent-module cycle that PR 1
    surfaced). The dispatched facade is invoked with
    ``step.args | {"dry_run": True}``, returning a ``RefactorResult``
    JSON envelope which we project into ``StepPreview.changes /
    diagnostics_delta / failure``.

    Unknown tool → ``INVALID_ARGUMENT`` failure. Facade exception →
    ``INTERNAL_ERROR`` failure (wrapped, never propagated). Malformed
    payload → ``INTERNAL_ERROR`` failure.

    v1.6 P4 (Plan 4): replaces the previous hardcoded empty StepPreview
    that lied to the LLM about every step's effect.
    """
    del project_root  # facade picks up project_root via its own get_project_root().
    from serena.tools.scalpel_facades import _FACADE_DISPATCH

    handler = _FACADE_DISPATCH.get(step.tool)
    if handler is None:
        return StepPreview(
            step_index=step_index,
            tool=step.tool,
            changes=(),
            diagnostics_delta=_empty_diagnostics_delta(),
            failure=FailureInfo(
                stage="_dry_run_one_step",
                reason=f"Unknown tool {step.tool!r}; not registered in _FACADE_DISPATCH.",
                code=ErrorCode.INVALID_ARGUMENT,
                recoverable=False,
            ),
        )
    args = {**(step.args or {}), "dry_run": True}
    try:
        raw_payload = handler(**args)
    except Exception as exc:  # noqa: BLE001 — surface as failure
        return StepPreview(
            step_index=step_index,
            tool=step.tool,
            changes=(),
            diagnostics_delta=_empty_diagnostics_delta(),
            failure=FailureInfo(
                stage="_dry_run_one_step",
                reason=f"Facade {step.tool!r} raised: {exc}",
                code=ErrorCode.INTERNAL_ERROR,
                recoverable=True,
            ),
        )
    try:
        payload = json.loads(raw_payload)
    except Exception as exc:  # noqa: BLE001
        return StepPreview(
            step_index=step_index,
            tool=step.tool,
            changes=(),
            diagnostics_delta=_empty_diagnostics_delta(),
            failure=FailureInfo(
                stage="_dry_run_one_step",
                reason=f"Facade {step.tool!r} returned invalid JSON: {exc}",
                code=ErrorCode.INTERNAL_ERROR,
                recoverable=True,
            ),
        )
    if not isinstance(payload, dict):
        return StepPreview(
            step_index=step_index,
            tool=step.tool,
            changes=(),
            diagnostics_delta=_empty_diagnostics_delta(),
            failure=FailureInfo(
                stage="_dry_run_one_step",
                reason=f"Facade {step.tool!r} returned non-object payload {type(payload).__name__}.",
                code=ErrorCode.INTERNAL_ERROR,
                recoverable=True,
            ),
        )
    return StepPreview(
        step_index=step_index,
        tool=step.tool,
        changes=_payload_to_step_changes(payload),
        diagnostics_delta=_payload_to_diagnostics_delta(payload),
        failure=_payload_to_failure(payload),
    )


def _derive_annotation_groups(
    workspace_edit: dict[str, Any],
) -> tuple[AnnotationGroup, ...]:
    """Project an LSP ``WorkspaceEdit.changeAnnotations`` map into ``AnnotationGroup``s.

    Each top-level annotation id becomes one group; ``edit_ids`` enumerates
    the annotation ids of every ``AnnotatedTextEdit`` (or resource op) that
    references it. Order is the iteration order of ``changeAnnotations``,
    which Python preserves for dicts since 3.7. Empty / missing
    ``changeAnnotations`` returns an empty tuple.
    """
    annotations = workspace_edit.get("changeAnnotations") or {}
    if not isinstance(annotations, dict):
        return ()
    # Build {annotation_id: [edit_ids]} by walking every edit that points at it.
    edit_ids_by_anno: dict[str, list[str]] = {aid: [] for aid in annotations}
    for dc in workspace_edit.get("documentChanges") or []:
        if not isinstance(dc, dict):
            continue
        if "kind" in dc:
            anno_id = dc.get("annotationId")
            if isinstance(anno_id, str) and anno_id in edit_ids_by_anno:
                edit_ids_by_anno[anno_id].append(anno_id)
            continue
        for edit in dc.get("edits") or []:
            if not isinstance(edit, dict):
                continue
            anno_id = edit.get("annotationId")
            if isinstance(anno_id, str) and anno_id in edit_ids_by_anno:
                edit_ids_by_anno[anno_id].append(anno_id)
    groups: list[AnnotationGroup] = []
    for anno_id, meta in annotations.items():
        if not isinstance(meta, dict):
            continue
        label_raw = meta.get("label")
        label = label_raw if isinstance(label_raw, str) else anno_id
        needs_raw = meta.get("needsConfirmation", False)
        needs_confirmation = bool(needs_raw)
        groups.append(AnnotationGroup(
            label=label,
            needs_confirmation=needs_confirmation,
            edit_ids=tuple(edit_ids_by_anno[anno_id]),
        ))
    return tuple(groups)


def _filter_workspace_edit_by_labels(
    workspace_edit: dict[str, Any],
    accepted_labels: set[str],
) -> dict[str, Any]:
    """Build a new WorkspaceEdit containing only edits annotated with accepted labels.

    Walks ``documentChanges`` (per LSP §3.17 the modern shape; ``changes`` map
    cannot carry ``annotationId``s so it's preserved verbatim if present but
    is not subject to the filter — Stage 1G clippy adapter and every Stage 2A
    facade that integrates manual review will use ``documentChanges``).

    Annotation lookup goes ``edit.annotationId → annotations[id].label``, so an
    accepted *label* admits every edit that carries any annotation id whose
    label is in ``accepted_labels``. Edits with no ``annotationId`` are dropped
    (manual mode treats unannotated edits as part of an implicit "unknown" group
    that is never accepted).
    """
    annotations = workspace_edit.get("changeAnnotations") or {}
    if not isinstance(annotations, dict):
        annotations = {}
    # Accepted annotation ids = ids whose label is in accepted_labels.
    accepted_ids: set[str] = set()
    for anno_id, meta in annotations.items():
        if not isinstance(meta, dict):
            continue
        label_raw = meta.get("label")
        label = label_raw if isinstance(label_raw, str) else anno_id
        if label in accepted_labels:
            accepted_ids.add(anno_id)

    filtered: dict[str, Any] = {}
    if "changes" in workspace_edit:
        # ``changes`` map has no per-edit annotationId; preserved verbatim.
        filtered["changes"] = workspace_edit["changes"]
    if accepted_ids and annotations:
        filtered["changeAnnotations"] = {
            aid: meta for aid, meta in annotations.items() if aid in accepted_ids
        }
    new_doc_changes: list[dict[str, Any]] = []
    for dc in workspace_edit.get("documentChanges") or []:
        if not isinstance(dc, dict):
            continue
        if "kind" in dc:
            anno_id = dc.get("annotationId")
            if isinstance(anno_id, str) and anno_id in accepted_ids:
                new_doc_changes.append(dc)
            continue
        kept_edits: list[dict[str, Any]] = []
        for edit in dc.get("edits") or []:
            if not isinstance(edit, dict):
                continue
            anno_id = edit.get("annotationId")
            if isinstance(anno_id, str) and anno_id in accepted_ids:
                kept_edits.append(edit)
        if kept_edits:
            new_doc_changes.append({
                "textDocument": dc.get("textDocument") or {},
                "edits": kept_edits,
            })
    if new_doc_changes:
        filtered["documentChanges"] = new_doc_changes
    return filtered


class ScalpelDryRunComposeTool(Tool):
    """PREFERRED: preview a chain of refactor steps without committing any.

    When ``confirmation_mode='manual'`` (Q4 §6.3 line 211 — the v1.1
    optional override the surrounding paragraph rejects for MVP), the
    tool short-circuits application, persists a ``PendingTransaction`` to
    the disk-backed pending-tx store, and returns ``awaiting_confirmation=True``
    so the caller routes through ``scalpel_confirm_annotations`` next.
    """

    PREVIEW_TTL_SECONDS = 300  # 5-min, per §5.5

    def apply(
        self,
        steps: list[dict[str, Any]],
        fail_fast: bool = True,
        confirmation_mode: Literal["auto", "manual"] = "auto",
        workspace_edit: dict[str, Any] | None = None,
    ) -> str:
        """Preview a chain of refactor steps without committing any.
        Returns transaction_id; call scalpel_transaction_commit to apply.

        :param steps: ordered list of {tool, args} dicts.
        :param fail_fast: stop at the first failing step (default True).
        :param confirmation_mode: 'auto' (default, unchanged behaviour) or
            'manual' (Q4 §6.3 line 211; persists pending tx, expects a
            follow-up scalpel_confirm_annotations call).
        :param workspace_edit: aggregate LSP WorkspaceEdit whose
            changeAnnotations seed the manual-mode pending tx; ignored when
            confirmation_mode='auto'.
        :return: JSON ComposeResult.
        """
        if confirmation_mode == "manual":
            return self._apply_manual_mode(workspace_edit or {})
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

    def _apply_manual_mode(self, workspace_edit: dict[str, Any]) -> str:
        """Persist a ``PendingTransaction`` and short-circuit application.

        Q4 §6.3 line 211 — the v1.1 optional override: the LLM passed
        ``confirmation_mode='manual'``, so every annotation group is staged
        on disk for ``scalpel_confirm_annotations`` to filter rather than
        being applied here. Returns a JSON envelope carrying the
        ``transaction_id`` + ``awaiting_confirmation=True`` plus a snapshot
        of the derived groups so the caller can reason about what to accept.
        """
        runtime = ScalpelRuntime.instance()
        raw_id = runtime.transaction_store().begin()
        txn_id = f"txn_{raw_id}"
        groups = _derive_annotation_groups(workspace_edit)
        runtime.pending_tx_store().put(PendingTransaction(
            id=txn_id, groups=groups, workspace_edit=workspace_edit,
        ))
        envelope = {
            "transaction_id": txn_id,
            "awaiting_confirmation": True,
            "expires_at": time.time() + self.PREVIEW_TTL_SECONDS,
            "groups": [
                {
                    "label": g.label,
                    "needs_confirmation": g.needs_confirmation,
                    "edit_ids": list(g.edit_ids),
                }
                for g in groups
            ],
        }
        import json as _json  # local import keeps top-level deps unchanged
        return _json.dumps(envelope, indent=2)


# ---------------------------------------------------------------------------
# Leaf 06: ScalpelConfirmAnnotationsTool — manual-review confirmation tool
# ---------------------------------------------------------------------------


class ScalpelConfirmAnnotationsTool(Tool):
    """PREFERRED: apply only the accepted annotation groups of a manual-mode pending transaction.

    See docs/design/mvp/open-questions/q4-changeannotations-auto-accept.md
    §6.3 line 211 (the v1.1 endorsement of optional manual review — the
    surrounding paragraph rejects this for MVP; only line 211 carries the
    v1.1 endorsement).
    """

    def apply(self, transaction_id: str, accept: list[str]) -> str:
        """Apply only the accepted annotation groups of a manual-mode
        pending transaction. Rejected groups have zero side effects.

        :param transaction_id: id returned by scalpel_dry_run_compose with
            confirmation_mode='manual'.
        :param accept: list of annotation labels to apply; empty = abandon.
        :return: JSON {transaction_id, applied_groups, rejected_groups,
            applied_edits, error_code?}.
        """
        # ``_apply_workspace_edit_to_disk`` is imported at module top via
        # ``serena.tools.facade_support`` (v1.6 Plan 0) — the prior lazy
        # import was kept to avoid the ``scalpel_primitives <->
        # scalpel_facades`` cycle, which is now broken.
        import json as _json

        runtime = ScalpelRuntime.instance()
        store = runtime.pending_tx_store()
        pending = store.get(transaction_id)
        if pending is None:
            return _json.dumps({
                "error_code": "UNKNOWN_TRANSACTION",
                "transaction_id": transaction_id,
            }, indent=2)
        accept_set = set(accept)
        applied_groups = [g.label for g in pending.groups if g.label in accept_set]
        rejected_groups = [g.label for g in pending.groups if g.label not in accept_set]
        filtered_edit = _filter_workspace_edit_by_labels(
            pending.workspace_edit, accept_set,
        )
        applied_count = (
            _apply_workspace_edit_to_disk(filtered_edit) if accept_set else 0
        )
        store.discard(transaction_id)
        return _json.dumps({
            "transaction_id": transaction_id,
            "applied_groups": applied_groups,
            "rejected_groups": rejected_groups,
            "applied_edits": applied_count,
        }, indent=2)


# ---------------------------------------------------------------------------
# T6: ScalpelRollbackTool + ScalpelTransactionRollbackTool
# ---------------------------------------------------------------------------


def _strip_txn_prefix(txn_id: str) -> str:
    """Strip the 'txn_' presentation prefix added by dry_run_compose.

    Tests pass raw store ids; production callers pass the prefixed form.
    """
    if txn_id.startswith("txn_"):
        return txn_id[len("txn_"):]
    return txn_id


class ScalpelRollbackTool(Tool):
    """PREFERRED: undo a refactor by checkpoint_id (idempotent).

    Restores edits to disk via the captured pre-edit snapshot and marks the
    checkpoint reverted in the store. Returns warnings for any irreversible
    resource operations (e.g., delete with no captured snapshot).

    Snapshot capture landed in v1.6 P1; this on-disk inverse-applier landed
    in v1.7 P7 (Plan 3-A). Idempotent — second call against the same
    checkpoint is a no-op.
    """

    def apply(self, checkpoint_id: str) -> str:
        """Undo a refactor by checkpoint_id. Idempotent: second call is no-op.

        Restores edits to disk via the captured pre-edit snapshot and marks
        the checkpoint reverted in the store. Returns warnings for any
        irreversible resource operations (e.g., delete with no captured
        snapshot).

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
        # Idempotent contract: if this checkpoint has already been rolled
        # back in this process, short-circuit to no_op without re-running the
        # inverse-applier (which would otherwise rewrite the snapshot atop
        # the same content for a no-op disk effect but a misleading
        # ``applied=True``).
        if getattr(ckpt, "reverted", False):
            return RefactorResult(
                applied=False,
                no_op=True,
                diagnostics_delta=_empty_diagnostics_delta(),
                checkpoint_id=checkpoint_id,
            ).model_dump_json(indent=2)
        # v1.7 P7 — call the real inverse-applier BEFORE marking the
        # checkpoint reverted. The applier restores per-URI content from the
        # captured snapshot; resource ops (create / delete / rename) are
        # reversed in reverse documentChanges order.
        ok, _warnings = inverse_apply_checkpoint(checkpoint_id)
        if ok:
            # Flip the reverted flag so subsequent calls are no-ops.
            ckpt.reverted = True
        return RefactorResult(
            applied=bool(ok),
            no_op=not ok,
            diagnostics_delta=_empty_diagnostics_delta(),
            checkpoint_id=checkpoint_id,
        ).model_dump_json(indent=2)


class ScalpelTransactionRollbackTool(Tool):
    """PREFERRED: undo all checkpoints in a transaction in reverse order (idempotent).

    Restores edits to disk via each checkpoint's captured pre-edit snapshot,
    walking steps in reverse chronological order so dependent edits unwind
    cleanly. Reverses resource ops (create / delete / rename) per step and
    marks each checkpoint reverted in the store for idempotency. Returns
    warnings for any irreversible resource operations (e.g., delete with no
    captured snapshot).

    Snapshot capture landed in v1.6 P1; this on-disk inverse-applier landed
    in v1.7 P7 (Plan 3-A).
    """

    def apply(self, transaction_id: str) -> str:
        """Undo all checkpoints in a transaction (from dry_run_compose) in
        reverse order. Idempotent.

        Restores edits to disk via each checkpoint's captured pre-edit
        snapshot, walking steps in reverse chronological order so dependent
        edits unwind cleanly. Reverses resource ops per step and returns
        warnings for any irreversible resource operations.

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
        # Walk steps in REVERSE chronological order so each step's inverse
        # runs against the interim disk state produced by the next-newer
        # step's already-reverted edit. v1.7 P7 — calls the real
        # inverse-applier per step.
        for cid in reversed(member_ids):
            ckpt = ckpt_store.get(cid)
            if ckpt is None:
                ok = False
            elif getattr(ckpt, "reverted", False):
                # Already reverted in a prior call — preserve idempotency.
                ok = False
            else:
                applied_ok, _warnings = inverse_apply_checkpoint(cid)
                if applied_ok:
                    ckpt.reverted = True
                ok = applied_ok
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
    """PREFERRED: probe LSP servers — indexing state, registered capabilities, version."""

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


# Per-language fallback allow-list of executeCommand verbs.
# Consulted only when a server's ``executeCommandProvider.commands`` field
# is absent or empty (spec § 4.6 / DLp5: R2 — under-advertising servers).
# The live allowlist is read at request time from each server's
# ServerCapabilities and dynamic registrations via
# MultiServerCoordinator.execute_command_allowlist().
_EXECUTE_COMMAND_FALLBACK: dict[str, frozenset[str]] = {
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
    """PREFERRED: server-specific JSON-RPC pass-through, allowlisted per language.

    The live allowlist is read at request time from each server's
    ``executeCommandProvider.commands`` (ServerCapabilities) and from
    dynamic registrations (``client/registerCapability`` events with
    method ``workspace/executeCommand``).  The static
    ``_EXECUTE_COMMAND_FALLBACK`` is used only when a server has not
    populated either source (spec § 4.6 / DLp5).
    """

    DEFAULT_LANGUAGE: str = "python"  # cluster-prefix discipline §5.3

    def apply(
        self,
        command: str,
        arguments: list[Any] | None = None,
        language: str | None = None,
        allow_out_of_workspace: bool = False,
    ) -> str:
        """Server-specific JSON-RPC pass-through, allowlisted per
        LanguageStrategy. Power-user escape hatch.

        :param command: the workspace/executeCommand verb (e.g.
            'rust-analyzer.runFlycheck').
        :param arguments: positional arguments forwarded as-is.
        :param language: language name (e.g. 'rust', 'python'); inferred when None.
        :param allow_out_of_workspace: skip workspace-boundary check.
        :return: JSON RefactorResult.
        """
        del allow_out_of_workspace  # T8: pass-through escape hatch only
        from solidlsp.ls_config import Language

        arguments = arguments or []
        chosen_language = language or self.DEFAULT_LANGUAGE
        if chosen_language not in _EXECUTE_COMMAND_FALLBACK:
            return _failure_result(
                ErrorCode.INVALID_ARGUMENT,
                "scalpel_execute_command",
                f"Unknown language {chosen_language!r}; "
                f"expected one of {sorted(_EXECUTE_COMMAND_FALLBACK)}.",
                recoverable=False,
            ).model_dump_json(indent=2)

        # Build the live allowlist: union of all servers' live commands
        # (ServerCapabilities + dynamic registrations), falling back to
        # the static _EXECUTE_COMMAND_FALLBACK when no live data is found.
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

        runtime = ScalpelRuntime.instance()
        coord = runtime.coordinator_for(lang_enum, project_root)
        per_language_fallback = _EXECUTE_COMMAND_FALLBACK[chosen_language]
        # Union allowlists from all servers in the pool.
        allowlist: frozenset[str] = frozenset()
        for server_id in coord.servers:
            allowlist = allowlist | coord.execute_command_allowlist(
                server_id, per_language_fallback
            )
        # If no server returned commands, fall back to the static set.
        if not allowlist:
            allowlist = per_language_fallback

        if command not in allowlist:
            failure = FailureInfo(
                stage="scalpel_execute_command",
                reason=(
                    f"Command {command!r} is not in the {chosen_language!r} "
                    "allowlist.  The live allowlist is derived from "
                    "executeCommandProvider.commands in each server's "
                    "ServerCapabilities; the fallback is "
                    "vendor/serena/src/serena/tools/scalpel_primitives.py:"
                    "_EXECUTE_COMMAND_FALLBACK."
                ),
                code=ErrorCode.CAPABILITY_NOT_AVAILABLE,
                recoverable=True,
                candidates=tuple(sorted(allowlist)[:5]),
            )
            return RefactorResult(
                applied=False,
                diagnostics_delta=_empty_diagnostics_delta(),
                failure=failure,
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
    """PREFERRED: reload plugin/capability registry from disk (no server restart)."""

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


# ---------------------------------------------------------------------------
# v1.1.1 Leaf 03 — ScalpelInstallLspServersTool
# ---------------------------------------------------------------------------


# Per-language installer registry. v1.1.1 shipped marksman; v1.2
# back-ports rust-analyzer / pylsp / basedpyright / ruff / clippy.
#
# Keys are unique installer identifiers — the registry maps each to a
# SINGLE installer class per the v1.1.1 contract. ``python`` resolves
# to pylsp (the primary Python LSP); ``python-basedpyright`` and
# ``python-ruff`` are secondary slots so the MCP tool can probe / install
# them independently. ``rust`` resolves to rust-analyzer; ``rust-clippy``
# is the Rust lint counterpart. The compound keys keep the contract one
# language-id → one installer (KISS) without losing the ability to drive
# every supported LSP server from the same MCP tool.
#
# The mapping lives here (rather than auto-discovering installer
# subclasses) so the MCP surface is explicit about which languages the
# tool will probe.
def _installer_registry() -> dict[str, type]:
    from serena.installer.basedpyright_installer import BasedpyrightInstaller
    from serena.installer.clangd_installer import ClangdInstaller
    from serena.installer.clippy_installer import ClippyInstaller
    from serena.installer.csharp_ls_installer import CsharpLsInstaller
    from serena.installer.gopls_installer import GoplsInstaller
    from serena.installer.jdtls_installer import JdtlsInstaller
    from serena.installer.lean_installer import LeanInstaller
    from serena.installer.marksman_installer import MarksmanInstaller
    from serena.installer.problog_installer import ProblogInstaller
    from serena.installer.prolog_installer import PrologInstaller
    from serena.installer.pylsp_installer import PylspInstaller
    from serena.installer.ruff_installer import RuffInstaller
    from serena.installer.rust_analyzer_installer import RustAnalyzerInstaller
    from serena.installer.smt2_installer import Smt2Installer
    from serena.installer.vtsls_installer import VtslsInstaller

    return {
        "markdown": MarksmanInstaller,
        "rust": RustAnalyzerInstaller,
        "python": PylspInstaller,
        "python-basedpyright": BasedpyrightInstaller,  # secondary Python LSP
        "python-ruff": RuffInstaller,                    # secondary Python LSP
        "rust-clippy": ClippyInstaller,                  # secondary Rust LSP
        "typescript": VtslsInstaller,
        "go": GoplsInstaller,
        "cpp": ClangdInstaller,
        "java": JdtlsInstaller,
        "lean": LeanInstaller,
        "smt2": Smt2Installer,
        "prolog": PrologInstaller,
        "problog": ProblogInstaller,
        "csharp": CsharpLsInstaller,
    }


def _decide_action(
    *,
    detected_present: bool,
    detected_version: str | None,
    latest: str | None,
) -> Literal["install", "update", "noop"]:
    if not detected_present:
        return "install"
    if latest is not None and detected_version is not None and latest != detected_version:
        return "update"
    return "noop"


class ScalpelInstallLspServersTool(Tool):
    """PREFERRED: install or update LSP servers (default dry-run; explicit consent gates execution)."""

    def apply(
        self,
        languages: list[str] | None = None,
        dry_run: bool = True,
        allow_install: bool = False,
        allow_update: bool = False,
    ) -> str:
        """Probe + optionally install/update LSP servers. Defaults to safe
        dry-run; pass dry_run=False AND allow_install=True (or allow_update=True)
        to actually run the install command.

        :param languages: subset of registered installer languages
            (e.g. ['markdown']); None probes every registered language.
        :param dry_run: when True (default), surface the planned argv
            tuple but never invoke subprocess.run.
        :param allow_install: explicit consent to run the install command
            for absent LSPs. Ignored when dry_run=True.
        :param allow_update: explicit consent to re-run the install
            command for outdated LSPs. Ignored when dry_run=True.
        :return: JSON dict {language: {detected, latest, action,
            command, dry_run, success?, stdout?, stderr?, return_code?}}.
        """
        import json as _json

        registry = _installer_registry()
        wanted = list(registry.keys()) if languages is None else list(languages)
        report: dict[str, dict[str, object]] = {}
        for lang in wanted:
            installer_cls = registry.get(lang)
            if installer_cls is None:
                report[lang] = {
                    "action": "skipped",
                    "reason": (
                        f"No installer registered for language {lang!r}; "
                        f"available: {sorted(registry)}."
                    ),
                }
                continue
            installer = installer_cls()
            try:
                detected = installer.detect_installed()
            except Exception as exc:  # noqa: BLE001 — surface as skipped
                report[lang] = {
                    "action": "skipped",
                    "reason": f"detect_installed raised {type(exc).__name__}: {exc}",
                }
                continue
            try:
                latest = installer.latest_available()
            except Exception:  # noqa: BLE001 — registry probe is best-effort
                latest = None
            try:
                command = installer._install_command()  # pyright: ignore[reportPrivateUsage]
            except NotImplementedError as exc:
                report[lang] = {
                    "action": "skipped",
                    "reason": str(exc),
                    "detected": {
                        "present": detected.present,
                        "version": detected.version,
                        "path": detected.path,
                    },
                    "latest": latest,
                }
                continue
            action = _decide_action(
                detected_present=detected.present,
                detected_version=detected.version,
                latest=latest,
            )
            entry: dict[str, object] = {
                "detected": {
                    "present": detected.present,
                    "version": detected.version,
                    "path": detected.path,
                },
                "latest": latest,
                "action": action,
                "command": list(command),
                "dry_run": True,
            }
            # Only invoke when BOTH gates are open. dry_run=True overrides
            # allow_install/allow_update so the LLM can audit the planned
            # command first (CLAUDE.md "executing actions with care").
            if not dry_run:
                if action == "install" and allow_install:
                    result = installer.install(allow_install=True)
                    _merge_install_result(entry, result)
                elif action == "update" and allow_update:
                    result = installer.update(allow_update=True)
                    _merge_install_result(entry, result)
                # action == "noop" or gate closed → keep dry_run=True.
            report[lang] = entry
        return _json.dumps(report, indent=2)


def _merge_install_result(entry: dict[str, object], result: object) -> None:
    """Project an :class:`InstallResult` into the per-language report row."""
    from serena.installer.installer import InstallResult

    if not isinstance(result, InstallResult):
        return
    entry["dry_run"] = result.dry_run
    entry["success"] = result.success
    entry["stdout"] = result.stdout
    entry["stderr"] = result.stderr
    entry["return_code"] = result.return_code
    entry["command"] = list(result.command_run)


__all__ = [
    "ScalpelApplyCapabilityTool",
    "ScalpelCapabilitiesListTool",
    "ScalpelCapabilityDescribeTool",
    "ScalpelConfirmAnnotationsTool",
    "ScalpelDryRunComposeTool",
    "ScalpelExecuteCommandTool",
    "ScalpelInstallLspServersTool",
    "ScalpelReloadPluginsTool",
    "ScalpelRollbackTool",
    "ScalpelTransactionRollbackTool",
    "ScalpelWorkspaceHealthTool",
]
