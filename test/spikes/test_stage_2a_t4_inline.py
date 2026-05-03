"""Stage 2A T5 — InlineTool tests."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import InlineTool
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def _make_tool(project_root: Path) -> InlineTool:
    tool = InlineTool.__new__(InlineTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def test_inline_call_rust_dispatches_inline_call_kind(tmp_path):
    target = tmp_path / "lib.rs"
    target.write_text("fn helper() -> i32 { 1 }\nfn x() { let a = helper(); }\n")
    tool = _make_tool(tmp_path)
    fake_coord = MagicMock()

    async def _merge(**kwargs):
        assert kwargs["only"] == ["refactor.inline.call"]
        return [MagicMock(action_id="ra:1", title="inline", kind="refactor.inline.call",
                          provenance="rust-analyzer")]
    fake_coord.merge_code_actions = _merge
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(target),
            position={"line": 1, "character": 18},
            target="call", scope="single_call_site",
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True


def test_inline_variable_python_dispatches(tmp_path):
    target = tmp_path / "x.py"
    target.write_text("x = 1\nprint(x)\n")
    tool = _make_tool(tmp_path)
    fake_coord = MagicMock()

    async def _merge(**kwargs):
        assert kwargs["only"] == ["refactor.inline.variable"]
        return [MagicMock(action_id="rope:1", title="inline x", kind="refactor.inline.variable",
                          provenance="pylsp-rope")]
    fake_coord.merge_code_actions = _merge
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(target),
            position={"line": 0, "character": 0},
            target="variable", scope="single_call_site",
            language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True


def test_inline_single_call_site_requires_position(tmp_path):
    target = tmp_path / "x.py"
    target.write_text("\n")
    tool = _make_tool(tmp_path)
    out = tool.apply(
        file=str(target),
        target="call", scope="single_call_site",
        language="python",
    )
    payload = json.loads(out)
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"


def test_inline_unknown_target_fails(tmp_path):
    target = tmp_path / "x.py"
    target.write_text("\n")
    tool = _make_tool(tmp_path)
    out = tool.apply(
        file=str(target),
        position={"line": 0, "character": 0},
        target="bogus", scope="single_call_site",  # type: ignore[arg-type]
        language="python",
    )
    payload = json.loads(out)
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"


# ---------------------------------------------------------------------------
# v1.5 G7-C — sibling real-disk acid test.
# ---------------------------------------------------------------------------


def test_inline_real_disk_lands_inlined_value_on_disk(tmp_path):
    """Acid-test sibling: inline the helper() call site; assert the
    on-disk text replaced helper() with its body."""
    target = tmp_path / "lib.rs"
    target.write_text(
        "fn helper() -> i32 { 1 }\nfn x() { let a = helper(); }\n",
        encoding="utf-8",
    )
    before = target.read_text(encoding="utf-8")
    tool = _make_tool(tmp_path)
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    async def _merge(**_kw):
        return [MagicMock(
            action_id="ra:1", id="ra:1", title="inline",
            kind="refactor.inline.call", provenance="rust-analyzer",
            is_preferred=False,
        )]

    fake_coord.merge_code_actions = _merge
    fake_coord.get_action_edit = lambda _aid: {
        "changes": {
            target.as_uri(): [{
                "range": {
                    "start": {"line": 1, "character": 17},
                    "end": {"line": 1, "character": 25},
                },
                "newText": "1",
            }],
        },
    }
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(target),
            position={"line": 1, "character": 18},
            target="call", scope="single_call_site",
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    after = target.read_text(encoding="utf-8")
    assert after != before
    assert "let a = 1;" in after


def test_inline_workspace_boundary_blocked(tmp_path):
    tool = _make_tool(tmp_path)
    out = tool.apply(
        file=str(tmp_path.parent / "elsewhere.py"),
        position={"line": 0, "character": 0},
        target="call", scope="single_call_site",
        language="python",
    )
    payload = json.loads(out)
    assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
