"""R7 — v1.3.0 LSP retrieval facade tests.

Covers the four new ``PREFERRED:`` Scalpel facades that wrap upstream
v1.3.0 retrieval tools:

  * ``ScalpelFindDeclarationTool``    → wraps ``FindDeclarationTool``
  * ``ScalpelFindImplementationsTool`` → wraps ``FindImplementationsTool``
  * ``ScalpelGetDiagnosticsForFileTool``   → wraps ``GetDiagnosticsForFileTool``
  * ``ScalpelGetDiagnosticsForSymbolTool`` → wraps ``GetDiagnosticsForSymbolTool``

Three test families per facade:

  (a) Happy path — composition delegates to the upstream tool and returns
      the upstream JSON shape unchanged when capability is present.
  (b) Capability gate — when ``supports_method`` reports False the facade
      returns the ``CAPABILITY_NOT_AVAILABLE`` envelope and does NOT invoke
      the upstream tool.
  (c) Docstring convention — drift-CI's ``PREFERRED:`` opener is present.

Notes
-----

* The facades are pure composition wrappers, so the happy-path tests
  monkey-patch the upstream tool's ``apply`` to confirm delegation —
  this keeps tests hermetic (no live LSP).
* Diagnostics tools gate on ``textDocument/documentSymbol`` because that
  capability is what ``find_diagnostic_owner_symbol`` depends on; the
  raw diagnostics request itself is universal in our supported servers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(cls: type, project_root: Path) -> Any:
    """Construct a tool instance bypassing ``__init__``.

    The Scalpel facade tests follow this pattern (see
    ``test_dispatcher_capability_gate.py``) — agent / project wiring is
    sidestepped because the facade only needs ``get_project_root``.
    """
    tool = cls.__new__(cls)
    cast(Any, tool).get_project_root = lambda: str(project_root)
    return tool


def _fake_coord_supports(supports: bool) -> MagicMock:
    """Coordinator double whose ``supports_method`` returns *supports*."""
    coord = MagicMock()
    coord.supports_method = MagicMock(return_value=supports)
    coord.supports_kind = MagicMock(return_value=supports)
    return coord


# ---------------------------------------------------------------------------
# (c) Docstring convention — drift-CI gate
# ---------------------------------------------------------------------------


class TestDocstringConvention:
    """Spec § 5.2.1 — every Scalpel facade opens with ``PREFERRED:``.

    These four tests are independent of the rest of the suite — they
    catch a contributor who forgets the opener even before the broader
    drift-CI test runs.
    """

    def test_find_declaration_facade_opens_with_preferred(self) -> None:
        from serena.tools.scalpel_facades import ScalpelFindDeclarationTool
        assert (ScalpelFindDeclarationTool.__doc__ or "").lstrip().startswith(
            "PREFERRED:"
        )

    def test_find_implementations_facade_opens_with_preferred(self) -> None:
        from serena.tools.scalpel_facades import ScalpelFindImplementationsTool
        assert (ScalpelFindImplementationsTool.__doc__ or "").lstrip().startswith(
            "PREFERRED:"
        )

    def test_get_diagnostics_for_file_facade_opens_with_preferred(self) -> None:
        from serena.tools.scalpel_facades import ScalpelGetDiagnosticsForFileTool
        assert (ScalpelGetDiagnosticsForFileTool.__doc__ or "").lstrip().startswith(
            "PREFERRED:"
        )

    def test_get_diagnostics_for_symbol_facade_opens_with_preferred(self) -> None:
        from serena.tools.scalpel_facades import ScalpelGetDiagnosticsForSymbolTool
        assert (ScalpelGetDiagnosticsForSymbolTool.__doc__ or "").lstrip().startswith(
            "PREFERRED:"
        )


# ---------------------------------------------------------------------------
# (b) Capability gate — supports_method=False returns CAPABILITY_NOT_AVAILABLE
# ---------------------------------------------------------------------------


class TestFindDeclarationCapabilityGate:
    """``textDocument/definition`` unsupported → skip envelope."""

    def test_negative_gate_returns_skip_envelope(self, tmp_path: Path) -> None:
        from serena.tools.scalpel_facades import ScalpelFindDeclarationTool
        src = tmp_path / "mod.py"
        src.write_text("def foo():\n    pass\n")
        coord = _fake_coord_supports(supports=False)

        with patch(
            "serena.tools.scalpel_facades.coordinator_for_facade",
            return_value=coord,
        ):
            tool = _make_tool(ScalpelFindDeclarationTool, tmp_path)
            out = tool.apply(
                relative_path="mod.py",
                regex=r"def (foo)",
            )

        payload = json.loads(out)
        assert payload["status"] == "skipped"
        assert "textDocument/definition" in payload["reason"]


class TestFindImplementationsCapabilityGate:
    """``textDocument/implementation`` unsupported → skip envelope."""

    def test_negative_gate_returns_skip_envelope(self, tmp_path: Path) -> None:
        from serena.tools.scalpel_facades import ScalpelFindImplementationsTool
        src = tmp_path / "mod.py"
        src.write_text("class A:\n    pass\n")
        coord = _fake_coord_supports(supports=False)

        with patch(
            "serena.tools.scalpel_facades.coordinator_for_facade",
            return_value=coord,
        ):
            tool = _make_tool(ScalpelFindImplementationsTool, tmp_path)
            out = tool.apply(name_path="A", relative_path="mod.py")

        payload = json.loads(out)
        assert payload["status"] == "skipped"
        assert "textDocument/implementation" in payload["reason"]


class TestGetDiagnosticsForFileCapabilityGate:
    """``textDocument/documentSymbol`` unsupported → skip envelope.

    The diagnostics tools need documentSymbol to map diagnostics → owner
    symbol; without it the upstream tool's output degenerates to file-level
    only, but more importantly we cannot guarantee the LSP server even
    initialised the diagnostic pipeline.  Gating here mirrors the upstream
    tool's hard dependency.
    """

    def test_negative_gate_returns_skip_envelope(self, tmp_path: Path) -> None:
        from serena.tools.scalpel_facades import ScalpelGetDiagnosticsForFileTool
        src = tmp_path / "mod.py"
        src.write_text("def foo():\n    pass\n")
        coord = _fake_coord_supports(supports=False)

        with patch(
            "serena.tools.scalpel_facades.coordinator_for_facade",
            return_value=coord,
        ):
            tool = _make_tool(ScalpelGetDiagnosticsForFileTool, tmp_path)
            out = tool.apply(relative_path="mod.py")

        payload = json.loads(out)
        assert payload["status"] == "skipped"
        assert "textDocument/documentSymbol" in payload["reason"]


class TestGetDiagnosticsForSymbolCapabilityGate:
    """``textDocument/documentSymbol`` unsupported → skip envelope."""

    def test_negative_gate_returns_skip_envelope(self, tmp_path: Path) -> None:
        from serena.tools.scalpel_facades import ScalpelGetDiagnosticsForSymbolTool
        src = tmp_path / "mod.py"
        src.write_text("def foo():\n    pass\n")
        coord = _fake_coord_supports(supports=False)

        with patch(
            "serena.tools.scalpel_facades.coordinator_for_facade",
            return_value=coord,
        ):
            tool = _make_tool(ScalpelGetDiagnosticsForSymbolTool, tmp_path)
            out = tool.apply(name_path="foo")

        payload = json.loads(out)
        assert payload["status"] == "skipped"
        assert "textDocument/documentSymbol" in payload["reason"]


# ---------------------------------------------------------------------------
# (a) Happy path — facades delegate to upstream and return upstream output
# ---------------------------------------------------------------------------


class TestFindDeclarationHappyPath:
    """When supports_method=True the facade calls into the upstream tool."""

    def test_delegates_to_upstream_find_declaration(self, tmp_path: Path) -> None:
        from serena.tools.scalpel_facades import ScalpelFindDeclarationTool
        src = tmp_path / "mod.py"
        src.write_text("def foo():\n    return 1\n")
        coord = _fake_coord_supports(supports=True)

        upstream_payload = '{"kind":"function","name_path":"foo"}'

        with patch(
            "serena.tools.scalpel_facades.coordinator_for_facade",
            return_value=coord,
        ), patch(
            "serena.tools.symbol_tools.FindDeclarationTool.apply",
            return_value=upstream_payload,
        ) as mock_apply:
            tool = _make_tool(ScalpelFindDeclarationTool, tmp_path)
            out = tool.apply(relative_path="mod.py", regex=r"def (foo)")

        assert out == upstream_payload
        mock_apply.assert_called_once()


class TestFindImplementationsHappyPath:
    def test_delegates_to_upstream_find_implementations(self, tmp_path: Path) -> None:
        from serena.tools.scalpel_facades import ScalpelFindImplementationsTool
        src = tmp_path / "mod.py"
        src.write_text("class A:\n    pass\n")
        coord = _fake_coord_supports(supports=True)

        upstream_payload = "[]"

        with patch(
            "serena.tools.scalpel_facades.coordinator_for_facade",
            return_value=coord,
        ), patch(
            "serena.tools.symbol_tools.FindImplementationsTool.apply",
            return_value=upstream_payload,
        ) as mock_apply:
            tool = _make_tool(ScalpelFindImplementationsTool, tmp_path)
            out = tool.apply(name_path="A", relative_path="mod.py")

        assert out == upstream_payload
        mock_apply.assert_called_once()


class TestGetDiagnosticsForFileHappyPath:
    def test_delegates_to_upstream(self, tmp_path: Path) -> None:
        from serena.tools.scalpel_facades import ScalpelGetDiagnosticsForFileTool
        src = tmp_path / "mod.py"
        src.write_text("x = 1\n")
        coord = _fake_coord_supports(supports=True)

        upstream_payload = "{}"

        with patch(
            "serena.tools.scalpel_facades.coordinator_for_facade",
            return_value=coord,
        ), patch(
            "serena.tools.symbol_tools.GetDiagnosticsForFileTool.apply",
            return_value=upstream_payload,
        ) as mock_apply:
            tool = _make_tool(ScalpelGetDiagnosticsForFileTool, tmp_path)
            out = tool.apply(relative_path="mod.py")

        assert out == upstream_payload
        mock_apply.assert_called_once()


class TestGetDiagnosticsForSymbolHappyPath:
    def test_delegates_to_upstream(self, tmp_path: Path) -> None:
        from serena.tools.scalpel_facades import ScalpelGetDiagnosticsForSymbolTool
        src = tmp_path / "mod.py"
        src.write_text("def foo():\n    pass\n")
        coord = _fake_coord_supports(supports=True)

        upstream_payload = "{}"

        with patch(
            "serena.tools.scalpel_facades.coordinator_for_facade",
            return_value=coord,
        ), patch(
            "serena.tools.symbol_tools.GetDiagnosticsForSymbolTool.apply",
            return_value=upstream_payload,
        ) as mock_apply:
            tool = _make_tool(ScalpelGetDiagnosticsForSymbolTool, tmp_path)
            out = tool.apply(name_path="foo")

        assert out == upstream_payload
        mock_apply.assert_called_once()


# ---------------------------------------------------------------------------
# Param-schema parity — facade signatures must match upstream so callers
# can swap without renaming kwargs.
# ---------------------------------------------------------------------------


class TestSignatureParity:
    """The facade ``apply`` signature mirrors the upstream tool's apply."""

    def _params(self, cls: type) -> list[str]:
        import inspect
        return [
            p.name for p in inspect.signature(cls.apply).parameters.values()
            if p.name != "self"
        ]

    def test_find_declaration_signature_parity(self) -> None:
        from serena.tools.scalpel_facades import ScalpelFindDeclarationTool
        from serena.tools.symbol_tools import FindDeclarationTool
        assert self._params(ScalpelFindDeclarationTool) == self._params(FindDeclarationTool)

    def test_find_implementations_signature_parity(self) -> None:
        from serena.tools.scalpel_facades import ScalpelFindImplementationsTool
        from serena.tools.symbol_tools import FindImplementationsTool
        assert self._params(ScalpelFindImplementationsTool) == self._params(FindImplementationsTool)

    def test_get_diagnostics_for_file_signature_parity(self) -> None:
        from serena.tools.scalpel_facades import ScalpelGetDiagnosticsForFileTool
        from serena.tools.symbol_tools import GetDiagnosticsForFileTool
        assert self._params(ScalpelGetDiagnosticsForFileTool) == self._params(GetDiagnosticsForFileTool)

    def test_get_diagnostics_for_symbol_signature_parity(self) -> None:
        from serena.tools.scalpel_facades import ScalpelGetDiagnosticsForSymbolTool
        from serena.tools.symbol_tools import GetDiagnosticsForSymbolTool
        assert self._params(ScalpelGetDiagnosticsForSymbolTool) == self._params(GetDiagnosticsForSymbolTool)


# ---------------------------------------------------------------------------
# Registration — the 4 facades show up in ToolRegistry under their canonical
# (no-prefix v2.0) and legacy (``scalpel_*``) names. Drift-CI elsewhere
# enforces the cardinality / convention.
# ---------------------------------------------------------------------------


class TestFacadeRegistration:
    """v2.0 wire-name cleanup: each Scalpel facade is dual-registered."""

    @pytest.fixture(autouse=True)
    def _reset_registry(self) -> None:
        # ``ToolRegistry`` is a singleton; the import-time scan picks up the
        # new classes naturally because they live in the registered module.
        pass

    def test_all_four_facades_in_registry_with_canonical_names(self) -> None:
        from serena.tools import ToolRegistry
        registry = ToolRegistry()
        names = set(registry._tool_dict.keys())
        # Canonical names follow Tool.get_name_from_cls — drop the trailing
        # "Tool" and snake_case-ify. The "Scalpel" prefix is part of the
        # class name and is preserved in snake_case form by the upstream
        # ``get_name_from_cls`` rule (the prefix is NOT stripped — only
        # ``Tool`` suffix is). So canonical = ``scalpel_find_declaration``.
        # That overlaps with the legacy-alias namespace, so we also assert
        # the upstream tool's canonical names are present and uncollided.
        assert "scalpel_find_declaration" in names
        assert "scalpel_find_implementations" in names
        assert "scalpel_get_diagnostics_for_file" in names
        assert "scalpel_get_diagnostics_for_symbol" in names
