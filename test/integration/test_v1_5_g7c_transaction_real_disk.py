"""v1.5 G7-C — real-disk acid tests for transaction_commit, plus
informational-LSP tests for expand_macro and verify_after_refactor.

Spec § Test discipline gaps (lines 157-174). G7-C completes the
zero-coverage sweep for the 3 cross-cutting facades that are too
broad for G7-A or G7-B:

  * TransactionCommitTool — multi-step composite. Acid test:
    each per-step RefactorResult reports a real on-disk effect.
  * ExpandMacroTool — informational LSP query. Acid test:
    the returned ``language_findings`` contain the expansion AND
    dry_run=True is a true no-side-effect preview (G2 contract).
  * VerifyAfterRefactorTool — composite query. Acid test:
    runnable+flycheck stats are surfaced AND dry_run=True is a true
    no-side-effect preview (G2 contract).

For ``transaction_commit``, the test composes a 2-step transaction
that routes through change_visibility (which is one of the
17 facades the v0.3.0 applier wires to disk). After commit, both
files are read post-apply and content asserted — proves the
transaction's per-step result envelope honestly maps to on-disk
effects (not stamped applied=True with no mutation).

Tests use mocked coordinators so they're fast + deterministic. The
v0.3.0 applier remains real (it's the unit under test).

Authored-by: AI Hive®.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import (
    ExpandMacroTool,
    TransactionCommitTool,
    VerifyAfterRefactorTool,
)
from serena.tools.scalpel_runtime import ScalpelRuntime


# ---------------------------------------------------------------------------
# Shared fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


_T = TypeVar("_T")


def _make_tool(cls: type[_T], project_root: Path) -> _T:
    tool = cls.__new__(cls)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[attr-defined]
    return tool


def _action(action_id: str, title: str, kind: str) -> MagicMock:
    a = MagicMock()
    a.id = action_id
    a.action_id = action_id
    a.title = title
    a.is_preferred = False
    a.provenance = "rust-analyzer"
    a.kind = kind
    return a


def _replace_edit(uri: str, sl: int, sc: int, el: int, ec: int, new_text: str) -> dict[str, Any]:
    return {
        "changes": {
            uri: [{
                "range": {
                    "start": {"line": sl, "character": sc},
                    "end": {"line": el, "character": ec},
                },
                "newText": new_text,
            }],
        },
    }


# ---------------------------------------------------------------------------
# 1. TransactionCommitTool — 2-step composite, both real-disk.
# ---------------------------------------------------------------------------


def _coord_with_visibility_edit() -> MagicMock:
    """Mock coord that surfaces a Change-Visibility action whose
    resolved edit lands ``pub(crate) `` at line 0 column 0 of
    whichever file the most-recent merge_code_actions call
    targeted (so the same coord works across multi-step txns)."""
    coord = MagicMock()
    coord.supports_kind.return_value = True
    last_file: list[str] = []

    async def _merge(**kw: Any) -> list[Any]:
        last_file.append(kw["file"])
        return [_action(
            "ra:vis", "Change visibility to pub(crate)",
            "refactor.rewrite.change_visibility",
        )]

    coord.merge_code_actions = _merge

    def _resolve(_aid: str) -> dict[str, Any]:
        target_path = Path(last_file[-1])
        return _replace_edit(
            target_path.as_uri(), 0, 0, 0, 0, "pub(crate) ",
        )

    coord.get_action_edit = _resolve
    return coord


def _direct_change_visibility_dispatcher(project_root: Path):
    """A drop-in replacement for ``_FACADE_DISPATCH['change_visibility']``
    that constructs the tool with a real ``get_project_root`` shim
    (the production dispatcher uses ``cast(Any, None)`` as the agent
    so the freshly-constructed tool's ``self.agent`` is None).

    Used by the transaction-commit acid test — the txn router calls
    the dispatcher, which calls the freshly-constructed tool, which
    must be able to resolve its project root for the workspace
    boundary guard.
    """
    from serena.tools.scalpel_facades import ChangeVisibilityTool

    def _dispatch(**kw: Any) -> str:
        tool = ChangeVisibilityTool.__new__(ChangeVisibilityTool)
        tool.get_project_root = lambda: str(project_root)  # type: ignore[attr-defined]
        return tool.apply(**kw)

    return _dispatch


def test_g7c_transaction_commit_two_step_real_disk(tmp_path: Path) -> None:
    """Compose two change_visibility steps targeting two
    sibling files; commit; read both files post-apply; assert each
    file received its expected mutation.

    Proves the per-step ``applied=True`` contract is honest: the
    underlying applier was actually invoked for each step, and the
    files reflect those edits on disk.
    """
    src_a = tmp_path / "a.rs"
    src_b = tmp_path / "b.rs"
    src_a.write_text("fn alpha() {}\n", encoding="utf-8")
    src_b.write_text("fn beta() {}\n", encoding="utf-8")
    before_a = src_a.read_text(encoding="utf-8")
    before_b = src_b.read_text(encoding="utf-8")

    runtime = ScalpelRuntime.instance()
    txn_store = runtime.transaction_store()
    raw_id = txn_store.begin()
    txn_store.add_step(raw_id, {
        "tool": "change_visibility",
        "args": {
            "file": str(src_a),
            "position": {"line": 0, "character": 3},
            "target_visibility": "pub_crate",
            "language": "rust",
        },
    })
    txn_store.add_step(raw_id, {
        "tool": "change_visibility",
        "args": {
            "file": str(src_b),
            "position": {"line": 0, "character": 3},
            "target_visibility": "pub_crate",
            "language": "rust",
        },
    })

    coord = _coord_with_visibility_edit()
    tool = _make_tool(TransactionCommitTool, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ), patch.dict(
        "serena.tools.scalpel_facades._FACADE_DISPATCH",
        {"change_visibility": _direct_change_visibility_dispatcher(tmp_path)},
        clear=False,
    ):
        out = tool.apply(transaction_id=f"txn_{raw_id}")

    payload = json.loads(out)
    assert payload["transaction_id"] == f"txn_{raw_id}"
    assert len(payload["per_step"]) == 2, payload
    assert all(s["applied"] for s in payload["per_step"]), payload

    after_a = src_a.read_text(encoding="utf-8")
    after_b = src_b.read_text(encoding="utf-8")
    assert after_a != before_a, after_a
    assert after_b != before_b, after_b
    assert "pub(crate) fn alpha()" in after_a
    assert "pub(crate) fn beta()" in after_b


def test_g7c_transaction_commit_first_failure_aborts_remaining_steps(
    tmp_path: Path,
) -> None:
    """A failing step short-circuits the transaction; the second
    step's file is left unchanged on disk."""
    src_a = tmp_path / "a.rs"
    src_b = tmp_path / "b.rs"
    src_a.write_text("fn alpha() {}\n", encoding="utf-8")
    src_b.write_text("fn beta() {}\n", encoding="utf-8")
    before_b = src_b.read_text(encoding="utf-8")

    runtime = ScalpelRuntime.instance()
    txn_store = runtime.transaction_store()
    raw_id = txn_store.begin()
    txn_store.add_step(raw_id, {
        "tool": "change_visibility",
        "args": {
            "file": str(src_a),
            "position": {"line": 0, "character": 3},
            "target_visibility": "pub_crate",
            "language": "rust",
        },
    })
    txn_store.add_step(raw_id, {
        "tool": "change_visibility",
        "args": {
            "file": str(src_b),
            "position": {"line": 0, "character": 3},
            "target_visibility": "pub_crate",
            "language": "rust",
        },
    })

    coord = MagicMock()
    coord.supports_kind.return_value = True

    async def _merge(**_kw: Any) -> list[Any]:
        # No actions surfaced → SYMBOL_NOT_FOUND failure on step 1.
        return []

    coord.merge_code_actions = _merge
    coord.get_action_edit = lambda _aid: None

    tool = _make_tool(TransactionCommitTool, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ), patch.dict(
        "serena.tools.scalpel_facades._FACADE_DISPATCH",
        {"change_visibility": _direct_change_visibility_dispatcher(tmp_path)},
        clear=False,
    ):
        out = tool.apply(transaction_id=f"txn_{raw_id}")

    payload = json.loads(out)
    assert len(payload["per_step"]) == 1, payload
    assert payload["per_step"][0]["applied"] is False
    # b.rs untouched because step 2 never ran:
    assert src_b.read_text(encoding="utf-8") == before_b


# ---------------------------------------------------------------------------
# 2. ExpandMacroTool — informational LSP query
# ---------------------------------------------------------------------------


def test_g7c_expand_macro_returns_expansion_text(tmp_path: Path) -> None:
    """expand_macro is informational — assert the surfaced expansion
    appears in the response's language_findings (not on disk)."""
    src = tmp_path / "lib.rs"
    src.write_text("println!(\"hi\");\n", encoding="utf-8")

    coord = MagicMock()

    async def _expand(**_kw: Any) -> dict[str, Any]:
        return {"name": "println!", "expansion": "<expanded text>"}

    coord.expand_macro = _expand
    tool = _make_tool(ExpandMacroTool, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 0},
            language="rust",
        )

    payload = json.loads(out)
    assert payload["applied"] is True
    findings = payload.get("language_findings") or []
    assert any("println!" in f.get("message", "") for f in findings), findings
    assert any("<expanded text>" in f.get("message", "") for f in findings)


def test_g7c_expand_macro_dry_run_is_no_side_effect_preview(tmp_path: Path) -> None:
    """G2 (HI-12) safety contract: dry_run=True must not invoke the
    LSP. We assert that by checking ``coord.expand_macro`` was never
    awaited."""
    src = tmp_path / "lib.rs"
    src.write_text("println!(\"hi\");\n", encoding="utf-8")

    coord = MagicMock()
    expand_calls: list[Any] = []

    async def _expand(**kw: Any) -> dict[str, Any]:
        expand_calls.append(kw)
        return {"name": "x", "expansion": "y"}

    coord.expand_macro = _expand
    tool = _make_tool(ExpandMacroTool, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 0},
            language="rust",
            dry_run=True,
        )

    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload.get("preview_token") is not None
    assert expand_calls == [], (
        "G2 contract: dry_run must short-circuit before invoking the LSP; "
        f"coord.expand_macro was called: {expand_calls!r}"
    )


# ---------------------------------------------------------------------------
# 3. VerifyAfterRefactorTool — composite query
# ---------------------------------------------------------------------------


def test_g7c_verify_after_refactor_summary_surface(tmp_path: Path) -> None:
    """Verify the runnables + flycheck composite surfaces a summary
    in language_findings."""
    src = tmp_path / "lib.rs"
    src.write_text("fn x() {}\n", encoding="utf-8")

    coord = MagicMock()

    async def _runnables(**_kw: Any) -> list[Any]:
        return [{"label": "test ::x"}, {"label": "test ::y"}]

    async def _flycheck(**_kw: Any) -> dict[str, Any]:
        return {"diagnostics": [{"severity": 1}]}

    coord.fetch_runnables = _runnables
    coord.run_flycheck = _flycheck

    tool = _make_tool(VerifyAfterRefactorTool, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(file=str(src), language="rust")

    payload = json.loads(out)
    assert payload["applied"] is True
    findings = payload.get("language_findings") or []
    assert any(
        "runnables=2" in f.get("message", "")
        and "flycheck_diagnostics=1" in f.get("message", "")
        for f in findings
    ), findings


def test_g7c_verify_after_refactor_dry_run_is_no_side_effect_preview(
    tmp_path: Path,
) -> None:
    """G2 safety: dry_run must NOT trigger flycheck (which kicks off
    cargo check on disk) or runnables."""
    src = tmp_path / "lib.rs"
    src.write_text("fn x() {}\n", encoding="utf-8")

    coord = MagicMock()
    runnable_calls: list[Any] = []
    flycheck_calls: list[Any] = []

    async def _runnables(**kw: Any) -> list[Any]:
        runnable_calls.append(kw)
        return []

    async def _flycheck(**kw: Any) -> dict[str, Any]:
        flycheck_calls.append(kw)
        return {"diagnostics": []}

    coord.fetch_runnables = _runnables
    coord.run_flycheck = _flycheck

    tool = _make_tool(VerifyAfterRefactorTool, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(file=str(src), language="rust", dry_run=True)

    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload.get("preview_token") is not None
    assert runnable_calls == [], runnable_calls
    assert flycheck_calls == [], flycheck_calls
