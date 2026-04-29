"""Stream 6 / Leaf I — CsharpLsServer adapter unit tests.

These tests are *unit* level: they exercise the adapter's constants and
small introspection methods without spawning a real csharp-ls subprocess.
The end-to-end smoke (boot + initialize + documentSymbol round-trip) is
deferred until csharp-ls is confirmed on the host — csharp-ls requires
the .NET SDK and ``dotnet tool install --global csharp-ls``.

The adapter mirrors the ``JdtlsServer`` shape
(single-LSP-per-language, sync facade methods, ``server_id: ClassVar[str]``)
so this test suite is deliberately thin — the broader Stage 1A facade
contract is exercised by the multi-server tests once the strategy is
registered.
"""

from __future__ import annotations

import shutil
from typing import Any, cast

import pytest

from solidlsp.language_servers.csharp_ls_server import CsharpLsServer
from solidlsp.ls_config import Language, LanguageServerConfig
from solidlsp.settings import SolidLSPSettings


def test_server_id_constant_is_csharp_ls() -> None:
    """``server_id`` keys dynamic-capability registrations; must be stable."""
    assert CsharpLsServer.server_id == "csharp-ls"


def test_get_language_enum_instance_returns_csharp() -> None:
    """Identity tie-back to ``Language.CSHARP`` (per Stage 1E pattern)."""
    assert CsharpLsServer.get_language_enum_instance() == Language.CSHARP


def test_is_ignored_dirname_includes_csharp_build_dirs(tmp_path) -> None:
    """bin / obj / .vs / .nuget / TestResults / artifacts dominate C# project trees."""
    if shutil.which("csharp-ls") is None:
        pytest.skip("csharp-ls not on PATH; skipping adapter instantiation")
    cfg = LanguageServerConfig(code_language=Language.CSHARP)
    srv = CsharpLsServer(cfg, str(tmp_path), SolidLSPSettings())
    assert srv.is_ignored_dirname("bin") is True
    assert srv.is_ignored_dirname("obj") is True
    assert srv.is_ignored_dirname("packages") is True
    assert srv.is_ignored_dirname(".vs") is True
    assert srv.is_ignored_dirname(".nuget") is True
    assert srv.is_ignored_dirname("TestResults") is True
    assert srv.is_ignored_dirname("artifacts") is True
    # ``src`` is the standard C# source directory and must not be ignored.
    assert srv.is_ignored_dirname("src") is False
    # ``test`` and ``lib`` are common C# subdirectories not to skip.
    assert srv.is_ignored_dirname("test") is False


def test_initialize_params_advertise_workspace_apply_edit(tmp_path) -> None:
    """``workspace.applyEdit=True`` is essential for cross-file rename writes."""
    params = cast(dict[str, Any], CsharpLsServer._get_initialize_params(str(tmp_path)))
    workspace_caps = params["capabilities"]["workspace"]
    assert workspace_caps["applyEdit"] is True
    assert workspace_caps["workspaceEdit"]["documentChanges"] is True


def test_initialize_params_advertise_rename_with_prepare(tmp_path) -> None:
    """``rename.prepareSupport=True`` is required for workspace-rename UI."""
    params = cast(dict[str, Any], CsharpLsServer._get_initialize_params(str(tmp_path)))
    text_doc_caps = params["capabilities"]["textDocument"]
    assert text_doc_caps["rename"]["prepareSupport"] is True


def test_initialize_params_advertise_code_action_kinds(tmp_path) -> None:
    """csharp-ls code action kinds must include the C# refactor family."""
    params = cast(dict[str, Any], CsharpLsServer._get_initialize_params(str(tmp_path)))
    kinds: list[str] = params["capabilities"]["textDocument"]["codeAction"][
        "codeActionLiteralSupport"
    ]["codeActionKind"]["valueSet"]
    # Quick-fix
    assert "quickfix" in kinds
    # Import management
    assert "source.organizeImports" in kinds
    # Extract refactors
    assert "refactor.extract.method" in kinds
    assert "refactor.extract.variable" in kinds
    # Inline refactors
    assert "refactor.inline.method" in kinds
    # Rewrite refactors
    assert "refactor.rewrite" in kinds


def test_initialize_params_language_id_has_process_id(tmp_path) -> None:
    """``processId`` must be an int (validates the static method is callable)."""
    params = cast(dict[str, Any], CsharpLsServer._get_initialize_params(str(tmp_path)))
    assert "processId" in params
    assert isinstance(params["processId"], int)
