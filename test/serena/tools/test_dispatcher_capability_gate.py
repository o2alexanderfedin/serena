"""DLp3 + DLp4 — integration tests for the supports_kind / supports_method
gates in both the shared dispatchers and the 8 bespoke facade dispatch sites.

Spec reference: dynamic LSP capability spec § 4.5 (gate insertion) and
§ 6 rows P3 / P4 exit criteria.

DLp3 — both ``_dispatch_single_kind_facade`` and
``_python_dispatch_single_kind`` are exercised with a synthetic coordinator
that returns ``False`` for ``supports_kind``.

DLp4 — the 8 bespoke facades (split_file/Rust, extract, inline, rename,
imports_organize, tidy_structure, fix_lints, rename_heading) are exercised
with a synthetic coordinator that returns ``False`` for ``supports_kind`` /
``supports_method``.

Each test confirms:
  1. The CAPABILITY_NOT_AVAILABLE envelope shape (spec § 4.7).
  2. No ``merge_code_actions`` / ``merge_rename`` call is made.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any, TypeVar, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from serena.tools.scalpel_facades import (
    ChangeTypeShapeTool,
    ConvertToMethodObjectTool,
    ExtractTool,
    FixLintsTool,
    ImportsOrganizeTool,
    InlineTool,
    RenameHeadingTool,
    RenameTool,
    SplitFileTool,
    TidyStructureTool,
    _capability_not_available_envelope,
)
from serena.tools.scalpel_runtime import ScalpelRuntime


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_T = TypeVar("_T")


@pytest.fixture(autouse=True)
def _reset_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("O2_SCALPEL_CACHE", str(tmp_path / "cache"))
    ScalpelRuntime.reset_for_testing()
    yield
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
    coord.supports_method = MagicMock(return_value=supports)
    coord.merge_code_actions = AsyncMock(return_value=[])
    coord.merge_rename = AsyncMock(return_value=(None, []))
    coord.find_symbol_range = AsyncMock(return_value=None)
    return coord


def _make_tool(cls: type[_T], project_root: Path) -> Any:
    """Construct a tool instance bypassing __init__; returns Any so each call site
    can use the subclass-specific apply() signature without type unification across
    the imported tool union."""
    tool = cls.__new__(cls)
    cast(Any, tool).get_project_root = lambda: str(project_root)
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
        reason = env["reason"]
        assert isinstance(reason, str)
        assert "my.custom.kind" in reason


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
            tool = _make_tool(ChangeTypeShapeTool, tmp_path)
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
            tool = _make_tool(ChangeTypeShapeTool, tmp_path)
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
            tool = _make_tool(ChangeTypeShapeTool, tmp_path)
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
            tool = _make_tool(ConvertToMethodObjectTool, tmp_path)
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
            tool = _make_tool(ConvertToMethodObjectTool, tmp_path)
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
            tool = _make_tool(ConvertToMethodObjectTool, tmp_path)
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


# ---------------------------------------------------------------------------
# DLp4 — 8 bespoke facade negative-gate tests (spec § 4.5 P4)
# ---------------------------------------------------------------------------


class TestBespokeSplitFileRustGate:
    """SplitFileTool Rust arm: supports_kind=False → CAPABILITY_NOT_AVAILABLE."""

    def test_negative_gate_returns_skip_envelope(self, tmp_path: Path) -> None:
        src = tmp_path / "main.rs"
        src.write_text("mod foo {}\n")
        coord = _fake_coord(supports=False)

        with patch(
            "serena.tools.scalpel_facades.coordinator_for_facade",
            return_value=coord,
        ):
            tool = _make_tool(SplitFileTool, tmp_path)
            out = tool.apply(
                file=str(src),
                groups={"new_mod": ["foo"]},
                language="rust",
            )

        payload = json.loads(out)
        assert payload["status"] == "skipped"
        assert "refactor.extract.module" in payload["reason"]
        assert payload["language"] == "rust"
        coord.merge_code_actions.assert_not_called()


class TestBespokeExtractGate:
    """ExtractTool: supports_kind=False → CAPABILITY_NOT_AVAILABLE."""

    def test_negative_gate_returns_skip_envelope(self, tmp_path: Path) -> None:
        src = tmp_path / "main.rs"
        src.write_text("fn add(a: i32, b: i32) -> i32 { a + b }\n")
        coord = _fake_coord(supports=False)
        # find_symbol_range must return a valid range so the gate is reached.
        coord.find_symbol_range = AsyncMock(return_value={
            "start": {"line": 0, "character": 0},
            "end": {"line": 0, "character": 10},
        })

        with patch(
            "serena.tools.scalpel_facades.coordinator_for_facade",
            return_value=coord,
        ):
            tool = _make_tool(ExtractTool, tmp_path)
            out = tool.apply(
                file=str(src),
                name_path="add",
                target="function",
                language="rust",
            )

        payload = json.loads(out)
        assert payload["status"] == "skipped"
        assert "lsp_does_not_support_" in payload["reason"]
        assert payload["language"] == "rust"
        coord.merge_code_actions.assert_not_called()


class TestBespokeInlineGate:
    """InlineTool: supports_kind=False → CAPABILITY_NOT_AVAILABLE."""

    def test_negative_gate_returns_skip_envelope(self, tmp_path: Path) -> None:
        src = tmp_path / "main.rs"
        src.write_text("fn foo() { let x = 1; }\n")
        coord = _fake_coord(supports=False)

        with patch(
            "serena.tools.scalpel_facades.coordinator_for_facade",
            return_value=coord,
        ):
            tool = _make_tool(InlineTool, tmp_path)
            out = tool.apply(
                file=str(src),
                target="variable",
                scope="single_call_site",
                position={"line": 0, "character": 12},
                language="rust",
            )

        payload = json.loads(out)
        assert payload["status"] == "skipped"
        assert "lsp_does_not_support_" in payload["reason"]
        assert payload["language"] == "rust"
        coord.merge_code_actions.assert_not_called()


class TestBespokeRenameGate:
    """RenameTool: supports_method=False → CAPABILITY_NOT_AVAILABLE."""

    def test_negative_gate_returns_skip_envelope(self, tmp_path: Path) -> None:
        src = tmp_path / "main.rs"
        src.write_text("fn old_name() {}\n")
        coord = _fake_coord(supports=False)
        # _resolve_symbol_position must return a position so the gate is reached.
        coord.list_document_symbols = AsyncMock(return_value=[
            {"name": "old_name", "range": {
                "start": {"line": 0, "character": 3},
                "end": {"line": 0, "character": 11},
            }, "selectionRange": {
                "start": {"line": 0, "character": 3},
                "end": {"line": 0, "character": 11},
            }, "kind": 12},
        ])

        with patch(
            "serena.tools.scalpel_facades.coordinator_for_facade",
            return_value=coord,
        ), patch.object(
            RenameTool,
            "_resolve_symbol_position",
            return_value={"line": 0, "character": 3},
        ):
            tool = _make_tool(RenameTool, tmp_path)
            out = tool.apply(
                file=str(src),
                name_path="old_name",
                new_name="new_name",
                language="rust",
            )

        payload = json.loads(out)
        assert payload["status"] == "skipped"
        assert "textDocument/rename" in payload["reason"]
        assert payload["language"] == "rust"
        coord.merge_rename.assert_not_called()


class TestBespokeImportsOrganizeGate:
    """ImportsOrganizeTool: supports_kind=False → CAPABILITY_NOT_AVAILABLE."""

    def test_negative_gate_returns_skip_envelope(self, tmp_path: Path) -> None:
        src = tmp_path / "mod.py"
        src.write_text("import os\nimport sys\n")
        coord = _fake_coord(supports=False)

        with patch(
            "serena.tools.scalpel_facades.coordinator_for_facade",
            return_value=coord,
        ):
            tool = _make_tool(ImportsOrganizeTool, tmp_path)
            out = tool.apply(
                files=[str(src)],
                language="python",
            )

        payload = json.loads(out)
        assert payload["status"] == "skipped"
        assert "source.organizeImports" in payload["reason"]
        assert payload["language"] == "python"
        coord.merge_code_actions.assert_not_called()


class TestBespokeTidyStructureGate:
    """TidyStructureTool: supports_kind=False → no merge_code_actions calls."""

    def test_negative_gate_skips_all_kinds(self, tmp_path: Path) -> None:
        src = tmp_path / "main.rs"
        src.write_text("struct Foo { b: i32, a: i32 }\n")
        coord = _fake_coord(supports=False)

        with patch(
            "serena.tools.scalpel_facades.coordinator_for_facade",
            return_value=coord,
        ):
            tool = _make_tool(TidyStructureTool, tmp_path)
            out = tool.apply(
                file=str(src),
                position={"line": 0, "character": 7},
                language="rust",
            )

        # All kinds skipped → no actions → no_op=True result (not a skip envelope).
        payload = json.loads(out)
        # Should return no_op (all kinds gated out) rather than a skipped envelope.
        assert payload.get("no_op") is True or payload.get("status") == "skipped"
        coord.merge_code_actions.assert_not_called()


class TestBespokeFixLintsGate:
    """FixLintsTool: supports_kind=False → CAPABILITY_NOT_AVAILABLE."""

    def test_negative_gate_returns_skip_envelope(self, tmp_path: Path) -> None:
        src = tmp_path / "lint_me.py"
        src.write_text("import os\nx=1\n")
        coord = _fake_coord(supports=False)

        with patch(
            "serena.tools.scalpel_facades.coordinator_for_facade",
            return_value=coord,
        ):
            tool = _make_tool(FixLintsTool, tmp_path)
            out = tool.apply(file=str(src))

        payload = json.loads(out)
        assert payload["status"] == "skipped"
        assert "source.fixAll.ruff" in payload["reason"]
        assert payload["language"] == "python"
        coord.merge_code_actions.assert_not_called()


class TestBespokeRenameHeadingGate:
    """RenameHeadingTool: supports_method=False → CAPABILITY_NOT_AVAILABLE."""

    def test_negative_gate_returns_skip_envelope(self, tmp_path: Path) -> None:
        src = tmp_path / "doc.md"
        src.write_text("# My Heading\n\nSome text.\n")
        coord = _fake_coord(supports=False)

        with patch(
            "serena.tools.scalpel_facades.coordinator_for_facade",
            return_value=coord,
        ):
            tool = _make_tool(RenameHeadingTool, tmp_path)
            out = tool.apply(
                file=str(src),
                heading="My Heading",
                new_name="New Heading",
            )

        payload = json.loads(out)
        assert payload["status"] == "skipped"
        assert "textDocument/rename" in payload["reason"]
        assert payload["language"] == "markdown"
        assert payload.get("server_id") == "marksman"
        coord.merge_rename.assert_not_called()
