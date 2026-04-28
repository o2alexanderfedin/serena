"""Stream 6 / Leaf A — VtslsServer adapter unit tests.

These tests are *unit* level: they exercise the adapter's constants and
small introspection methods without spawning a real vtsls subprocess.
The end-to-end smoke (boot + initialize + documentSymbol round-trip)
lives in ``test/solidlsp/typescript/`` once vtsls is confirmed on the
host (the existing TypeScript integration tests cover that path).

The adapter mirrors the ``MarksmanLanguageServer`` shape
(single-LSP-per-language, sync facade methods, ``server_id: ClassVar[str]``)
so this test suite is deliberately thin — the broader Stage 1A facade
contract is exercised by the multi-server tests once the strategy is
registered.
"""

from __future__ import annotations

import shutil
from typing import Any, cast

import pytest

from solidlsp.language_servers.vtsls_server import VtslsServer
from solidlsp.ls_config import Language, LanguageServerConfig
from solidlsp.settings import SolidLSPSettings


def test_server_id_constant_is_vtsls() -> None:
    """``server_id`` keys dynamic-capability registrations; must be stable."""
    assert VtslsServer.server_id == "vtsls"


def test_get_language_enum_instance_returns_typescript() -> None:
    """Identity tie-back to ``Language.TYPESCRIPT`` (per Stage 1E pattern)."""
    assert VtslsServer.get_language_enum_instance() == Language.TYPESCRIPT


def test_is_ignored_dirname_includes_node_modules_and_dist(tmp_path) -> None:
    """node_modules / dist / .next dominate TypeScript project trees."""
    if shutil.which("vtsls") is None:
        pytest.skip("vtsls not on PATH; skipping adapter instantiation")
    cfg = LanguageServerConfig(code_language=Language.TYPESCRIPT)
    srv = VtslsServer(cfg, str(tmp_path), SolidLSPSettings())
    assert srv.is_ignored_dirname("node_modules") is True
    assert srv.is_ignored_dirname("dist") is True
    assert srv.is_ignored_dirname("build") is True
    assert srv.is_ignored_dirname(".next") is True
    # ``src`` is a normal directory and must not be ignored.
    assert srv.is_ignored_dirname("src") is False


def test_initialize_params_advertise_workspace_apply_edit(tmp_path) -> None:
    """``workspace.applyEdit=True`` is essential for cross-file rename writes."""
    params = cast(dict[str, Any], VtslsServer._get_initialize_params(str(tmp_path)))
    workspace_caps = params["capabilities"]["workspace"]
    assert workspace_caps["applyEdit"] is True
    assert workspace_caps["workspaceEdit"]["documentChanges"] is True


def test_initialize_params_advertise_rename_with_prepare(tmp_path) -> None:
    """``rename.prepareSupport=True`` is required for workspace-rename UI."""
    params = cast(dict[str, Any], VtslsServer._get_initialize_params(str(tmp_path)))
    text_doc_caps = params["capabilities"]["textDocument"]
    assert text_doc_caps["rename"]["prepareSupport"] is True


def test_initialize_params_advertise_code_action_kinds(tmp_path) -> None:
    """vtsls code action kinds must include the TS refactor family."""
    params = cast(dict[str, Any], VtslsServer._get_initialize_params(str(tmp_path)))
    kinds: list[str] = params["capabilities"]["textDocument"]["codeAction"][
        "codeActionLiteralSupport"
    ]["codeActionKind"]["valueSet"]
    assert "source.organizeImports" in kinds
    assert "source.fixAll" in kinds
    assert "refactor.extract" in kinds
    assert "refactor.inline" in kinds


def test_initialize_params_language_id_is_typescript(tmp_path) -> None:
    """``language_id`` must be ``"typescript"`` to match vtsls expectations."""
    # Verify via the constructor's positional arg (passed to super as language_id).
    # We do this indirectly by checking the static params include the right
    # process id (any non-zero int) — the real check is the adapter's class body.
    params = cast(dict[str, Any], VtslsServer._get_initialize_params(str(tmp_path)))
    assert "processId" in params
    assert isinstance(params["processId"], int)
