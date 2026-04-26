"""T1 — §11.6 multi-server schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from serena.refactoring.multi_server import (
    MergedCodeAction,
    MultiServerBroadcastResult,
    ServerTimeoutWarning,
    SuppressedAlternative,
)


def test_merged_code_action_minimal() -> None:
    a = MergedCodeAction(
        id="ca-1",
        title="Organize imports",
        kind="source.organizeImports",
        disabled_reason=None,
        is_preferred=False,
        provenance="ruff",
    )
    assert a.id == "ca-1"
    assert a.suppressed_alternatives == []


def test_merged_code_action_with_suppressed() -> None:
    s = SuppressedAlternative(
        title="Organize imports",
        provenance="pylsp-rope",
        reason="lower_priority",
    )
    a = MergedCodeAction(
        id="ca-2",
        title="Organize imports",
        kind="source.organizeImports",
        disabled_reason=None,
        is_preferred=True,
        provenance="ruff",
        suppressed_alternatives=[s],
    )
    assert a.suppressed_alternatives[0].provenance == "pylsp-rope"
    assert a.suppressed_alternatives[0].reason == "lower_priority"


def test_provenance_literal_rejects_unknown() -> None:
    with pytest.raises(ValidationError):
        MergedCodeAction(
            id="ca-3",
            title="x",
            kind="quickfix",
            disabled_reason=None,
            is_preferred=False,
            provenance="jedi",  # not in the closed Literal set
        )


def test_provenance_literal_includes_pylsp_mypy_for_v1_1_compat() -> None:
    """pylsp-mypy is in the Literal so v1.1 can re-introduce it without
    a schema migration. Stage 1D never CONSTRUCTS one (P5a / SUMMARY §6
    drops pylsp-mypy from the active set), but the schema permits it."""
    a = MergedCodeAction(
        id="ca-4",
        title="t",
        kind="quickfix",
        disabled_reason=None,
        is_preferred=False,
        provenance="pylsp-mypy",
    )
    assert a.provenance == "pylsp-mypy"


def test_suppressed_alternative_reason_literal() -> None:
    with pytest.raises(ValidationError):
        SuppressedAlternative(title="x", provenance="ruff", reason="some_other_reason")
    for r in ("lower_priority", "duplicate_title", "duplicate_edit"):
        SuppressedAlternative(title="x", provenance="ruff", reason=r)


def test_server_timeout_warning_defaults() -> None:
    w = ServerTimeoutWarning(server="ruff", method="textDocument/codeAction", timeout_ms=2000, after_ms=2050)
    assert w.timeout_ms == 2000
    assert w.after_ms == 2050


def test_multi_server_broadcast_result_round_trip() -> None:
    r = MultiServerBroadcastResult(
        responses={"ruff": [{"title": "x"}]},
        timeouts=[ServerTimeoutWarning(server="pylsp-rope", method="textDocument/codeAction", timeout_ms=2000, after_ms=2010)],
        errors={"basedpyright": "boom"},
    )
    dumped = r.model_dump()
    rebuilt = MultiServerBroadcastResult(**dumped)
    assert rebuilt.responses["ruff"] == [{"title": "x"}]
    assert rebuilt.timeouts[0].server == "pylsp-rope"
    assert rebuilt.errors["basedpyright"] == "boom"


def test_module_exports_via_refactoring_package() -> None:
    from serena.refactoring import (
        MergedCodeAction as MA,
        MultiServerBroadcastResult as MR,
        ServerTimeoutWarning as STW,
        SuppressedAlternative as SA,
    )
    assert MA is MergedCodeAction
    assert MR is MultiServerBroadcastResult
    assert STW is ServerTimeoutWarning
    assert SA is SuppressedAlternative
