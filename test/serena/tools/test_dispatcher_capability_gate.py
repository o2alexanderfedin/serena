"""DLp3 — integration tests for the supports_kind gate in the two shared
facade dispatchers.

Spec reference: dynamic LSP capability spec § 4.5 (gate insertion) and
§ 6 row P3 exit criterion.

Both ``_dispatch_single_kind_facade`` and ``_python_dispatch_single_kind``
are exercised with a synthetic coordinator that returns ``False`` for
``supports_kind``.  The test confirms:
  1. The CAPABILITY_NOT_AVAILABLE envelope shape (spec § 4.7).
  2. The positive path (supports_kind=True) is unchanged — dispatcher
     proceeds to the merge_code_actions call (producing SYMBOL_NOT_FOUND,
     not a skipped envelope).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from serena.tools.scalpel_facades import (
    ScalpelChangeTypeShapeTool,
    ScalpelConvertToMethodObjectTool,
    _capability_not_available_envelope,
)
from serena.tools.scalpel_runtime import ScalpelRuntime


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("O2_SCALPEL_CACHE", str(tmp_path / "cache"))
    ScalpelRuntime.reset_for_testing()
    yield  # type: ignore[misc]
    ScalpelRuntime.reset_for_testing()


def _fake_coord(supports: bool) -> MagicMock:
    """Minimal fake coordinator whose supports_kind returns *supports*.

    ``merge_code_actions`` is an AsyncMock returning [] so:
    - when supports=False the gate fires before the call, letting the test
      assert_not_called() successfully.
    - when supports=True the dispatcher proceeds to the call (returning []),
      which triggers SYMBOL_NOT_FOUND — confirming the gate was passed.
    """
    coord = MagicMock()
    coord.supports_kind = MagicMock(return_value=supports)
    coord.merge_code_actions = AsyncMock(return_value=[])
    return coord


def _make_tool(cls, project_root: Path):
    tool = cls.__new__(cls)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


# ---------------------------------------------------------------------------
# _capability_not_available_envelope — unit check
# ---------------------------------------------------------------------------


class TestCapabilityNotAvailableEnvelope:
    """The helper produces the correct spec § 4.7 shape."""

    def test_shape_with_server_id(self) -> None:
        env = _capability_not_available_envelope(
            language="rust",
            kind="refactor.extract.function",
            server_id="rust-analyzer",
        )
        assert env["status"] == "skipped"
        assert env["reason"] == "lsp_does_not_support_refactor.extract.function"
        assert env["server_id"] == "rust-analyzer"
        assert env["language"] == "rust"
        assert env["kind"] == "refactor.extract.function"

    def test_shape_without_server_id_defaults_none(self) -> None:
        env = _capability_not_available_envelope(
            language="python", kind="source.organizeImports"
        )
        assert env["server_id"] is None
        assert env["status"] == "skipped"

    def test_reason_embeds_kind(self) -> None:
        env = _capability_not_available_envelope(language="rust", kind="my.custom.kind")
        assert "my.custom.kind" in env["reason"]


# ---------------------------------------------------------------------------
# _dispatch_single_kind_facade — negative gate (Rust path)
# ---------------------------------------------------------------------------


class TestDispatchSingleKindFacadeNegativeGate:
    """supports_kind=False → return CAPABILITY_NOT_AVAILABLE envelope,
    no merge_code_actions call."""

    def test_negative_gate_returns_skip_envelope(self, tmp_path: Path) -> None:
        src = tmp_path / "main.rs"
        src.write_text("fn main() {}\n")
        coord = _fake_coord(supports=False)

        with patch(
            "serena.tools.scalpel_facades.coordinator_for_facade",
            return_value=coord,
        ):
            tool = _make_tool(ScalpelChangeTypeShapeTool, tmp_path)
            out = tool.apply(
                file=str(src),
                position={"line": 0, "character": 4},
                target_shape="named_struct",
                language="rust",
            )

        payload = json.loads(out)
        assert payload["status"] == "skipped", f"Expected 'skipped', got: {payload}"
        assert "lsp_does_not_support_" in payload["reason"]
        assert payload["language"] == "rust"
        assert "kind" in payload

    def test_negative_gate_does_not_call_merge_code_actions(
        self, tmp_path: Path
    ) -> None:
        src = tmp_path / "main.rs"
        src.write_text("fn main() {}\n")
        coord = _fake_coord(supports=False)

        with patch(
            "serena.tools.scalpel_facades.coordinator_for_facade",
            return_value=coord,
        ):
            tool = _make_tool(ScalpelChangeTypeShapeTool, tmp_path)
            tool.apply(
                file=str(src),
                position={"line": 0, "character": 4},
                target_shape="named_struct",
                language="rust",
            )

        coord.merge_code_actions.assert_not_called()

    def test_positive_gate_proceeds_to_merge(self, tmp_path: Path) -> None:
        """supports_kind=True → gate passes, dispatcher calls merge_code_actions.

        merge_code_actions returns [] here, so SYMBOL_NOT_FOUND is returned —
        confirming the call was made and the code advanced past the gate.
        """
        src = tmp_path / "main.rs"
        src.write_text("fn main() {}\n")
        coord = _fake_coord(supports=True)

        with patch(
            "serena.tools.scalpel_facades.coordinator_for_facade",
            return_value=coord,
        ):
            tool = _make_tool(ScalpelChangeTypeShapeTool, tmp_path)
            out = tool.apply(
                file=str(src),
                position={"line": 0, "character": 4},
                target_shape="named_struct",
                language="rust",
            )

        payload = json.loads(out)
        # Must NOT be a skipped envelope — it should be SYMBOL_NOT_FOUND.
        assert payload.get("status") != "skipped", (
            "Positive gate must not return a skipped envelope"
        )
        assert "failure" in payload


# ---------------------------------------------------------------------------
# _python_dispatch_single_kind — negative gate (Python path)
# ---------------------------------------------------------------------------


class TestPythonDispatchSingleKindNegativeGate:
    """supports_kind=False → return CAPABILITY_NOT_AVAILABLE envelope,
    no merge_code_actions call."""

    def test_negative_gate_returns_skip_envelope(self, tmp_path: Path) -> None:
        src = tmp_path / "module.py"
        src.write_text("class Foo:\n    def bar(self): pass\n")
        coord = _fake_coord(supports=False)

        with patch(
            "serena.tools.scalpel_facades.coordinator_for_facade",
            return_value=coord,
        ):
            tool = _make_tool(ScalpelConvertToMethodObjectTool, tmp_path)
            out = tool.apply(
                file=str(src),
                position={"line": 1, "character": 8},
            )

        payload = json.loads(out)
        assert payload["status"] == "skipped", f"Expected 'skipped', got: {payload}"
        assert payload["language"] == "python"
        assert "lsp_does_not_support_" in payload["reason"]
        assert "kind" in payload

    def test_negative_gate_does_not_call_merge_code_actions(
        self, tmp_path: Path
    ) -> None:
        src = tmp_path / "module.py"
        src.write_text("class Foo:\n    def bar(self): pass\n")
        coord = _fake_coord(supports=False)

        with patch(
            "serena.tools.scalpel_facades.coordinator_for_facade",
            return_value=coord,
        ):
            tool = _make_tool(ScalpelConvertToMethodObjectTool, tmp_path)
            tool.apply(
                file=str(src),
                position={"line": 1, "character": 8},
            )

        coord.merge_code_actions.assert_not_called()

    def test_positive_gate_proceeds_to_merge(self, tmp_path: Path) -> None:
        """supports_kind=True → gate passes, dispatcher calls merge_code_actions."""
        src = tmp_path / "module.py"
        src.write_text("class Foo:\n    def bar(self): pass\n")
        coord = _fake_coord(supports=True)

        with patch(
            "serena.tools.scalpel_facades.coordinator_for_facade",
            return_value=coord,
        ):
            tool = _make_tool(ScalpelConvertToMethodObjectTool, tmp_path)
            out = tool.apply(
                file=str(src),
                position={"line": 1, "character": 8},
            )

        payload = json.loads(out)
        # Must NOT be a skipped envelope — SYMBOL_NOT_FOUND is expected.
        assert payload.get("status") != "skipped", (
            "Positive gate must not return a skipped envelope"
        )
        assert "failure" in payload
