"""Stream 6 / Leaf C — ClangdServer adapter unit tests.

These tests are *unit* level: they exercise the adapter's constants and
small introspection methods without spawning a real clangd subprocess.
The end-to-end smoke (boot + initialize + documentSymbol round-trip)
lives in ``test/solidlsp/cpp/`` once clangd is confirmed on the host
(the existing C++ integration tests cover that path).

The adapter mirrors the ``GoplsServer`` shape
(single-LSP-per-language, sync facade methods, ``server_id: ClassVar[str]``)
so this test suite is deliberately thin — the broader Stage 1A facade
contract is exercised by the multi-server tests once the strategy is
registered.
"""

from __future__ import annotations

import shutil
from typing import Any, cast

import pytest

from solidlsp.language_servers.clangd_server import ClangdServer
from solidlsp.ls_config import Language, LanguageServerConfig
from solidlsp.settings import SolidLSPSettings


def test_server_id_constant_is_clangd() -> None:
    """``server_id`` keys dynamic-capability registrations; must be stable."""
    assert ClangdServer.server_id == "clangd"


def test_get_language_enum_instance_returns_cpp() -> None:
    """Identity tie-back to ``Language.CPP`` (per Stage 1E pattern)."""
    assert ClangdServer.get_language_enum_instance() == Language.CPP


def test_is_ignored_dirname_includes_build_and_cmake_dirs(tmp_path) -> None:
    """build / CMakeFiles / third_party dominate C/C++ project trees."""
    if shutil.which("clangd") is None:
        pytest.skip("clangd not on PATH; skipping adapter instantiation")
    cfg = LanguageServerConfig(code_language=Language.CPP)
    srv = ClangdServer(cfg, str(tmp_path), SolidLSPSettings())
    assert srv.is_ignored_dirname("build") is True
    assert srv.is_ignored_dirname("CMakeFiles") is True
    assert srv.is_ignored_dirname("third_party") is True
    assert srv.is_ignored_dirname("vendor") is True
    assert srv.is_ignored_dirname(".cache") is True
    assert srv.is_ignored_dirname("cmake-build-debug") is True
    # ``src`` is a normal source directory and must not be ignored.
    assert srv.is_ignored_dirname("src") is False
    # ``include`` is a normal header directory and must not be ignored.
    assert srv.is_ignored_dirname("include") is False


def test_initialize_params_advertise_workspace_apply_edit(tmp_path) -> None:
    """``workspace.applyEdit=True`` is essential for cross-file rename writes."""
    params = cast(dict[str, Any], ClangdServer._get_initialize_params(str(tmp_path)))
    workspace_caps = params["capabilities"]["workspace"]
    assert workspace_caps["applyEdit"] is True
    assert workspace_caps["workspaceEdit"]["documentChanges"] is True


def test_initialize_params_advertise_rename_with_prepare(tmp_path) -> None:
    """``rename.prepareSupport=True`` is required for workspace-rename UI."""
    params = cast(dict[str, Any], ClangdServer._get_initialize_params(str(tmp_path)))
    text_doc_caps = params["capabilities"]["textDocument"]
    assert text_doc_caps["rename"]["prepareSupport"] is True


def test_initialize_params_advertise_code_action_kinds(tmp_path) -> None:
    """clangd code action kinds must include the C/C++ refactor family."""
    params = cast(dict[str, Any], ClangdServer._get_initialize_params(str(tmp_path)))
    kinds: list[str] = params["capabilities"]["textDocument"]["codeAction"][
        "codeActionLiteralSupport"
    ]["codeActionKind"]["valueSet"]
    assert "source.organizeImports" in kinds
    assert "source.fixAll.clangd" in kinds
    assert "refactor.extract" in kinds
    assert "refactor.inline" in kinds
    assert "quickfix" in kinds


def test_initialize_params_language_id_is_cpp(tmp_path) -> None:
    """``language_id`` must be ``"cpp"`` to match clangd expectations."""
    params = cast(dict[str, Any], ClangdServer._get_initialize_params(str(tmp_path)))
    assert "processId" in params
    assert isinstance(params["processId"], int)
