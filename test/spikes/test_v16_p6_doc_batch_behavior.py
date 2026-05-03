"""v1.6 P5 / Plan 5 — doc batch behavior tests.

8 RED tests for the small behavior changes that ride along the doc batch:

- 3 ``ExpandMacroTool.dry_run`` honoring tests (default applies, dry_run
  short-circuits and returns a preview token).
- 3 ``VerifyAfterRefactorTool.dry_run`` honoring tests (skip flycheck,
  skip runnables, return preview token).
- 3 threading tests (``generate_from_undefined.target_kind``,
  ``ignore_diagnostic.rule``, ``tidy_structure.scope``) — assert the post-merge
  filter or kind-restrict actually narrows the action list.

Plan source: docs/superpowers/plans/2026-04-29-stub-facade-fix/IMPLEMENTATION-PLANS.md  Plan 5
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from typing import Any, cast
import pytest

from serena.refactoring.checkpoints import CheckpointStore
from serena.tools.scalpel_facades import (
    ExpandMacroTool,
    GenerateFromUndefinedTool,
    IgnoreDiagnosticTool,
    TidyStructureTool,
    VerifyAfterRefactorTool,
)
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def _isolate_runtime() -> Iterator[None]:
    ScalpelRuntime.reset_for_testing()
    inst = ScalpelRuntime.instance()
    inst._checkpoint_store = CheckpointStore(disk_root=None)
    yield
    ScalpelRuntime.reset_for_testing()


def _make_tool(cls, project_root: Path) -> Any:
    tool = cls.__new__(cls)
    cast(Any, tool).get_project_root = lambda: str(project_root)
    return tool


# ---------------------------------------------------------------------------
# expand_macro dry_run honoring (3 tests)
# ---------------------------------------------------------------------------


def test_expand_macro_dry_run_returns_applied_false_with_preview_token(
    tmp_path: Path,
) -> None:
    src = tmp_path / "lib.rs"
    src.write_text('println!("hi");\n')
    tool = _make_tool(ExpandMacroTool, tmp_path)
    coord = MagicMock()

    expand_calls: list[Any] = []

    async def _expand(**kwargs):
        expand_calls.append(kwargs)
        return {"name": "println", "expansion": '{ ::std::println!("hi"); }'}

    coord.expand_macro = _expand
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src), position={"line": 0, "character": 7},
            language="rust", dry_run=True,
        )
    payload = json.loads(out)
    assert payload["applied"] is False, (
        "dry_run=True must NOT report applied=True"
    )
    assert payload["preview_token"], (
        "dry_run=True must return a non-empty preview_token"
    )
    # The macro probe should NOT be called when dry_run short-circuits.
    assert expand_calls == [], (
        "dry_run=True must skip the rust-analyzer expand_macro probe"
    )


def test_expand_macro_default_apply_true_returns_expansion(
    tmp_path: Path,
) -> None:
    src = tmp_path / "lib.rs"
    src.write_text('println!("hi");\n')
    tool = _make_tool(ExpandMacroTool, tmp_path)
    coord = MagicMock()

    async def _expand(**kwargs):
        del kwargs
        return {"name": "println", "expansion": '{ ::std::println!("hi"); }'}

    coord.expand_macro = _expand
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src), position={"line": 0, "character": 7},
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True, (
        "default dry_run=False must continue to call expand_macro"
    )
    assert payload["language_findings"], "expansion finding must be present"


# ---------------------------------------------------------------------------
# verify_after_refactor dry_run honoring (3 tests)
# ---------------------------------------------------------------------------


def _verify_coord_with_call_log() -> tuple[MagicMock, list[str]]:
    coord = MagicMock()
    calls: list[str] = []

    async def _runnables(**kwargs):
        del kwargs
        calls.append("runnables")
        return [{"label": "test mod::a", "kind": "test"}]

    async def _flycheck(**kwargs):
        del kwargs
        calls.append("flycheck")
        return {"diagnostics": []}

    coord.fetch_runnables = _runnables
    coord.run_flycheck = _flycheck
    return coord, calls


def test_verify_dry_run_skips_flycheck_call(tmp_path: Path) -> None:
    src = tmp_path / "lib.rs"
    src.write_text("\n")
    tool = _make_tool(VerifyAfterRefactorTool, tmp_path)
    coord, calls = _verify_coord_with_call_log()
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        tool.apply(file=str(src), language="rust", dry_run=True)
    assert "flycheck" not in calls, (
        "dry_run=True must skip the run_flycheck probe"
    )


def test_verify_dry_run_skips_runnables_call(tmp_path: Path) -> None:
    src = tmp_path / "lib.rs"
    src.write_text("\n")
    tool = _make_tool(VerifyAfterRefactorTool, tmp_path)
    coord, calls = _verify_coord_with_call_log()
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        tool.apply(file=str(src), language="rust", dry_run=True)
    assert "runnables" not in calls, (
        "dry_run=True must skip the fetch_runnables probe"
    )


def test_verify_dry_run_returns_preview_token_no_findings(
    tmp_path: Path,
) -> None:
    src = tmp_path / "lib.rs"
    src.write_text("\n")
    tool = _make_tool(VerifyAfterRefactorTool, tmp_path)
    coord, _calls = _verify_coord_with_call_log()
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(file=str(src), language="rust", dry_run=True)
    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload["preview_token"], (
        "dry_run=True must return a non-empty preview_token"
    )
    assert payload.get("language_findings") in (None, [], ()), (
        "dry_run=True must NOT surface verify_summary findings"
    )


# ---------------------------------------------------------------------------
# Threading tests — generate_from_undefined.target_kind filter
# ---------------------------------------------------------------------------


def _fake_action(*, title: str, kind: str = "quickfix.generate", server: str = "pylsp-rope"):
    a = MagicMock()
    a.title = title
    a.kind = kind
    a.provenance = server
    a.diagnostics = ()
    return a


def test_generate_from_undefined_threads_target_kind_to_action_filter(
    tmp_path: Path,
) -> None:
    src = tmp_path / "calc.py"
    src.write_text("from .x import y\n")
    tool = _make_tool(GenerateFromUndefinedTool, tmp_path)
    coord = MagicMock()
    coord.supports_kind = MagicMock(return_value=True)

    captured_actions: list[Any] = []

    async def _merge(**kwargs):
        del kwargs
        return [
            _fake_action(title="Function from undefined name 'foo'"),
            _fake_action(title="Class from undefined name 'foo'"),
            _fake_action(title="Variable from undefined name 'foo'"),
        ]

    coord.merge_code_actions = _merge

    # Capture the post-filter action list by patching apply_action_and_checkpoint.
    def _capture(_coord, action):
        captured_actions.append(action)
        return ("ckpt-1", {"changes": {}})

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ), patch(
        "serena.tools.scalpel_facades.apply_action_and_checkpoint",
        side_effect=_capture,
    ):
        tool.apply(
            file=str(src), position={"line": 0, "character": 0},
            target_kind="function", language="python",
        )
    # The filter should keep ONLY the 'function' action, so the winner that
    # gets resolved should have a title starting with 'function'.
    assert captured_actions, "at least one action should have survived the filter"
    assert captured_actions[0].title.lower().startswith("function"), (
        f"target_kind='function' must filter actions to function variants; "
        f"got first action title={captured_actions[0].title!r}"
    )


# ---------------------------------------------------------------------------
# Threading tests — ignore_diagnostic.rule filter
# ---------------------------------------------------------------------------


def test_ignore_diagnostic_threads_rule_to_action_filter(
    tmp_path: Path,
) -> None:
    src = tmp_path / "calc.py"
    src.write_text("import os\n")
    tool = _make_tool(IgnoreDiagnosticTool, tmp_path)
    coord = MagicMock()
    coord.supports_kind = MagicMock(return_value=True)

    def _action_with_diag(rule: str, title: str = "noqa"):
        a = MagicMock()
        a.title = title
        a.kind = "quickfix.ruff_noqa"
        a.provenance = "ruff"
        # diagnostics list may be tuples or dicts on the real LSP.
        a.diagnostics = ({"code": rule, "message": f"rule {rule}"},)
        return a

    captured_actions: list[Any] = []

    async def _merge(**kwargs):
        del kwargs
        return [
            _action_with_diag("E501"),
            _action_with_diag("W291"),
            _action_with_diag("F401"),
        ]

    coord.merge_code_actions = _merge

    def _capture(_coord, action):
        captured_actions.append(action)
        return ("ckpt-1", {"changes": {}})

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ), patch(
        "serena.tools.scalpel_facades.apply_action_and_checkpoint",
        side_effect=_capture,
    ):
        tool.apply(
            file=str(src), position={"line": 0, "character": 0},
            tool_name="ruff", rule="E501", language="python",
        )
    assert captured_actions, "at least one action should have survived the filter"
    rule_codes = [str(d.get("code")) for d in captured_actions[0].diagnostics]
    assert "E501" in rule_codes, (
        f"rule='E501' must filter actions to those whose diagnostics "
        f"include E501; got {rule_codes!r}"
    )


# ---------------------------------------------------------------------------
# Threading tests — tidy_structure.scope kind-restrict
# ---------------------------------------------------------------------------


def test_tidy_structure_threads_scope_to_kind_restrict(
    tmp_path: Path,
) -> None:
    src = tmp_path / "lib.rs"
    src.write_text("struct S { a: i32, b: i32 }\n")
    tool = _make_tool(TidyStructureTool, tmp_path)
    coord = MagicMock()
    coord.supports_kind = MagicMock(return_value=True)

    requested_kinds: list[tuple[str, ...]] = []

    async def _merge(**kwargs):
        only = tuple(kwargs.get("only") or ())
        requested_kinds.append(only)
        return []

    coord.merge_code_actions = _merge
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        tool.apply(
            file=str(src),
            position={"line": 0, "character": 7},
            scope="type", language="rust",
        )
    # When scope='type', the loop must restrict to the reorder_fields kind only.
    flat = tuple(k for kinds in requested_kinds for k in kinds)
    assert "refactor.rewrite.reorder_fields" in flat, (
        f"scope='type' should request reorder_fields; got {flat!r}"
    )
    # And it should NOT request reorder_impl_items / sort_items in 'type' scope.
    assert "refactor.rewrite.reorder_impl_items" not in flat, (
        f"scope='type' should NOT request reorder_impl_items; got {flat!r}"
    )
