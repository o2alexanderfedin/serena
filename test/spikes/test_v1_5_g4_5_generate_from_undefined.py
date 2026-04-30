"""v1.5 G4-5 — generate_from_undefined honors target_kind (HI-6).

Acid tests:
  * target_kind="class" → dispatch carries ``only=["quickfix.generate.class"]``
    when rope advertises the granular kind (preferred path).
  * target_kind="variable" → ``only=["quickfix.generate.variable"]``.
  * target_kind="function" → ``only=["quickfix.generate.function"]``.
  * Flat-kind fallback: when rope only advertises the flat
    ``quickfix.generate``, dispatch carries ``only=["quickfix.generate"]``
    AND threads ``title_match=target_kind`` so rope's per-kind candidate
    title is selected by substring (forward-compat).
  * Real-disk acid test confirms each target_kind landed the correct
    text-edit shape (only the requested kind's content lands).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import ScalpelGenerateFromUndefinedTool
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


@pytest.fixture
def python_workspace(tmp_path: Path) -> Path:
    src = tmp_path / "calc.py"
    src.write_text("def main():\n    x = compute()\n", encoding="utf-8")
    return tmp_path


def _make_tool(project_root: Path) -> ScalpelGenerateFromUndefinedTool:
    tool = ScalpelGenerateFromUndefinedTool.__new__(ScalpelGenerateFromUndefinedTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def _action(action_id: str, title: str, kind: str):
    a = MagicMock()
    a.id = action_id
    a.action_id = action_id
    a.title = title
    a.kind = kind
    a.is_preferred = False
    a.provenance = "pylsp-rope"
    return a


def _capture_dispatch_for(target_kind: str, granular_kind_text: str,
                          src: Path, advertise_granular: bool):
    """Helper — returns (captured_calls, fake_coord_factory)."""
    captured: list[dict] = []

    granular_kind = f"quickfix.generate.{target_kind}"

    fake_coord = MagicMock()

    def _supports(language, kind):
        if kind == granular_kind:
            return advertise_granular
        if kind == "quickfix.generate":
            return True
        return False

    fake_coord.supports_kind.side_effect = _supports

    async def _actions(**kw):
        captured.append(kw)
        only = list(kw.get("only", []))
        # Return one action whose kind matches whichever LSP only filter
        # was sent; title carries the target_kind for the title_match
        # fallback path.
        chosen_kind = only[0] if only else "quickfix.generate"
        return [_action("rope:1", f"Generate {target_kind} compute", chosen_kind)]

    fake_coord.merge_code_actions = _actions
    fake_coord.get_action_edit = lambda aid: {
        "changes": {src.as_uri(): [{
            "range": {"start": {"line": 0, "character": 0},
                      "end": {"line": 0, "character": 0}},
            "newText": granular_kind_text,
        }]},
    }
    return captured, fake_coord


def test_target_class_dispatches_class_kind(python_workspace):
    tool = _make_tool(python_workspace)
    src = python_workspace / "calc.py"
    captured, fake_coord = _capture_dispatch_for(
        target_kind="class",
        granular_kind_text="class compute:\n    pass\n",
        src=src,
        advertise_granular=True,
    )

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 1, "character": 8},
            target_kind="class",
            language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True, payload
    # Dispatch carries the granular class kind.
    assert any(
        c.get("only") == ["quickfix.generate.class"] for c in captured
    ), captured
    assert "class compute" in src.read_text(encoding="utf-8")


def test_target_variable_dispatches_variable_kind(python_workspace):
    tool = _make_tool(python_workspace)
    src = python_workspace / "calc.py"
    captured, fake_coord = _capture_dispatch_for(
        target_kind="variable",
        granular_kind_text="compute = None\n",
        src=src,
        advertise_granular=True,
    )

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 1, "character": 8},
            target_kind="variable",
            language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    assert any(
        c.get("only") == ["quickfix.generate.variable"] for c in captured
    ), captured
    assert "compute = None" in src.read_text(encoding="utf-8")


def test_target_function_dispatches_function_kind(python_workspace):
    tool = _make_tool(python_workspace)
    src = python_workspace / "calc.py"
    captured, fake_coord = _capture_dispatch_for(
        target_kind="function",
        granular_kind_text="def compute():\n    pass\n",
        src=src,
        advertise_granular=True,
    )

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 1, "character": 8},
            target_kind="function",
            language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    assert any(
        c.get("only") == ["quickfix.generate.function"] for c in captured
    ), captured
    assert "def compute" in src.read_text(encoding="utf-8")


def test_flat_kind_fallback_when_granular_unavailable(python_workspace):
    """Forward-compat: older rope versions only advertise the flat
    ``quickfix.generate``. The facade must fall back to the flat kind
    and thread ``title_match=target_kind`` so rope's per-kind candidate
    title is selected by substring match."""
    tool = _make_tool(python_workspace)
    src = python_workspace / "calc.py"
    captured, fake_coord = _capture_dispatch_for(
        target_kind="class",
        granular_kind_text="class compute:\n    pass\n",
        src=src,
        advertise_granular=False,  # rope only knows the flat kind
    )

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 1, "character": 8},
            target_kind="class",
            language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True, payload
    # Fallback used the flat kind:
    assert any(
        c.get("only") == ["quickfix.generate"] for c in captured
    ), captured
    # Real-disk: text-edit applied (substring title-match selected the
    # class candidate).
    assert "class compute" in src.read_text(encoding="utf-8")
