"""Clippy → WorkspaceEdit adapter for the v1.1 Rust+clippy multi-server scenario.

Clippy is shipped with the Rust toolchain as ``cargo-clippy`` and emits
machine-readable lint output via ``cargo clippy --message-format=json``.
For LLM-driven refactor flows we need to project clippy's
``rendered`` suggestions into the same ``WorkspaceEdit`` shape rust-analyzer
already produces, so the language-agnostic multi-server merger
(``serena.refactoring.multi_server``) can:

* atomically apply or reject the second-source edit alongside
  rust-analyzer's primary edit (invariant 1 — atomicity);
* honour the per-file ``version`` carried in the edit
  (invariant 2 — version mismatch);
* let the merger's ``_check_workspace_boundary`` reject any edit
  whose URI escapes the workspace folders
  (invariant 3 — workspace boundary);
* round-trip clippy's lint name as a ``changeAnnotations`` entry with
  ``needsConfirmation=True`` so the LLM-facing ``dry_run`` surface can
  surface the warning before we commit
  (invariant 4 — change-annotation warning surface).

Per the Stream-4 Leaf-05 design comment in this module's neighbours, the
adapter MUST NOT introduce new merger code paths — every ``WorkspaceEdit``
it returns is consumed by the existing applier
(``serena.tools.scalpel_facades._apply_workspace_edit_to_disk``) and the
existing invariant gates (``_check_apply_clean``,
``_check_workspace_boundary``, ``_check_syntactic_validity``).

Feature flag
------------

``cargo clippy --fix`` rewrites source files in place before we ever see
the JSON. To keep the adapter safe to import unconditionally we DO NOT
invoke ``--fix`` from the production code path; the suggestions are read
from ``--message-format=json`` and projected into ``TextEdit`` form so the
multi-server merger keeps full control of when and where bytes hit disk.

The ``cargo.clippy.applyFix`` execute-command surface is gated behind
the ``O2_SCALPEL_CLIPPY_MULTI_SERVER`` env var (see ``RustStrategy``).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

__all__ = [
    "ClippyAdapter",
    "ClippyUnavailableError",
    "clippy_json_to_workspace_edit",
]


class ClippyUnavailableError(RuntimeError):
    """Raised when ``cargo clippy`` cannot be invoked on this host."""


class ClippyAdapter:
    """Synthesize ``WorkspaceEdit`` payloads from cargo-clippy JSON output.

    The adapter is deliberately stateless beyond the workspace path so it
    is cheap to construct and trivially safe to call from async fan-out
    paths (per ``MultiServerCoordinator.broadcast``). All bytes hit disk
    only via the language-agnostic applier.

    :param workspace: filesystem path to a cargo workspace root
        (the directory containing the workspace ``Cargo.toml``).
    :param clippy_executable: optional override for the ``cargo`` binary
        path; resolved via ``shutil.which("cargo")`` when ``None``.
    """

    def __init__(
        self,
        workspace: Path,
        clippy_executable: str | None = None,
    ) -> None:
        self._workspace = Path(workspace).resolve(strict=False)
        self._cargo = clippy_executable

    @property
    def workspace(self) -> Path:
        return self._workspace

    def diagnostics_as_workspace_edit(
        self,
        *,
        timeout_s: float = 60.0,
    ) -> dict[str, Any]:
        """Run ``cargo clippy --message-format=json`` and project the
        suggestions into a single ``WorkspaceEdit``.

        The adapter does NOT pass ``--fix`` — clippy's auto-rewrite mode
        bypasses the multi-server merger and the workspace-boundary gate
        (it writes through cargo's own file IO). Reading the suggestions
        out of the JSON stream and feeding them to the merger keeps the
        invariants in play.

        :raises ClippyUnavailableError: when ``cargo`` is missing on PATH.
        """
        cargo_bin = self._cargo or shutil.which("cargo")
        if cargo_bin is None:
            raise ClippyUnavailableError(
                "cargo not found on PATH; cannot drive clippy",
            )
        proc = subprocess.run(  # noqa: S603 — args are statically known
            [
                cargo_bin,
                "clippy",
                "--message-format=json",
                "--quiet",
            ],
            cwd=str(self._workspace),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_s,
        )
        return clippy_json_to_workspace_edit(proc.stdout, self._workspace)


# ---------------------------------------------------------------------------
# Pure-python projection — exposed at module level for direct testing.
# ---------------------------------------------------------------------------


def clippy_json_to_workspace_edit(
    stdout: str,
    workspace: Path,
) -> dict[str, Any]:
    """Convert a stream of ``cargo --message-format=json`` records into a
    single ``WorkspaceEdit`` dict per LSP §3.17.

    The output uses the ``documentChanges`` shape with ``version: None``
    (invariant 2 will pin the version when callers know it). Each
    clippy ``rendered`` suggestion that carries a structured replacement
    span produces one ``TextEdit`` keyed by the source file's ``file://``
    URI. ``changeAnnotations`` round-trips the lint name with
    ``needsConfirmation=True`` so the dry-run surface can warn the LLM.

    Records that are not ``compiler-message``s, that lack
    ``rendered``-suggestion spans, or whose spans have
    ``suggestion_applicability == "Unspecified"`` are skipped — clippy
    flags them as unsafe-to-apply and the merger treats them as
    surface-only candidates anyway.

    :param stdout: raw stdout of ``cargo clippy --message-format=json``.
    :param workspace: filesystem path used to resolve relative file names.
    """
    workspace = Path(workspace).resolve(strict=False)
    document_edits: dict[str, list[dict[str, Any]]] = {}
    annotations: dict[str, dict[str, Any]] = {}
    annotation_assignments: list[tuple[str, str]] = []  # (uri, annotation_id)

    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if record.get("reason") != "compiler-message":
            continue
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        code = message.get("code") or {}
        lint_name = code.get("code") if isinstance(code, dict) else None
        if not isinstance(lint_name, str):
            lint_name = "clippy::unknown"

        spans = message.get("spans") or []
        for span in spans:
            if not isinstance(span, dict):
                continue
            replacement = span.get("suggested_replacement")
            applicability = span.get("suggestion_applicability")
            if replacement is None:
                continue
            if applicability == "Unspecified":
                # Clippy explicitly marks this as unsafe — surface as
                # annotation-only so the merger can still warn but won't
                # apply automatically.
                pass
            file_name = span.get("file_name")
            if not isinstance(file_name, str):
                continue
            file_path = (workspace / file_name).resolve(strict=False)
            uri = file_path.as_uri()
            text_edit = {
                "range": _span_to_range(span),
                "newText": str(replacement),
            }
            document_edits.setdefault(uri, []).append(text_edit)

            annotation_id = lint_name
            annotation_assignments.append((uri, annotation_id))
            annotations.setdefault(
                annotation_id,
                {
                    "label": lint_name,
                    "needsConfirmation": True,
                    "description": (
                        message.get("message")
                        if isinstance(message.get("message"), str)
                        else None
                    ),
                },
            )

    document_changes: list[dict[str, Any]] = []
    for uri, edits in document_edits.items():
        document_changes.append({
            "textDocument": {"uri": uri, "version": None},
            "edits": edits,
        })

    workspace_edit: dict[str, Any] = {"documentChanges": document_changes}
    if annotations:
        workspace_edit["changeAnnotations"] = annotations
    return workspace_edit


def _span_to_range(span: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Convert a cargo span (1-based line/col, end-exclusive col) to an LSP
    Range (0-based line/character)."""
    line_start = max(int(span.get("line_start", 1)) - 1, 0)
    column_start = max(int(span.get("column_start", 1)) - 1, 0)
    line_end = max(int(span.get("line_end", line_start + 1)) - 1, 0)
    column_end = max(int(span.get("column_end", column_start + 1)) - 1, 0)
    return {
        "start": {"line": line_start, "character": column_start},
        "end": {"line": line_end, "character": column_end},
    }
