"""v1.1.1 Leaf 01 — MarksmanLanguageServer adapter unit tests.

These tests are *unit* level: they exercise the adapter's constants and
small introspection methods without spawning a real marksman subprocess.
The end-to-end smoke (boot + initialize + documentSymbol round-trip)
lives at ``test/integration/test_marksman_smoke.py``.

The adapter mirrors the ``PylspServer`` shape (single-LSP-per-language,
sync facade methods, ``server_id: ClassVar[str]``) so this test suite is
deliberately thin — the broader Stage 1A facade contract is exercised
by the multi-server tests once the strategy is registered.
"""

from __future__ import annotations

import shutil
from typing import Any, cast

import pytest

from solidlsp.language_servers.marksman_server import MarksmanLanguageServer
from solidlsp.ls_config import Language, LanguageServerConfig
from solidlsp.settings import SolidLSPSettings


def test_server_id_constant_is_marksman() -> None:
    """``server_id`` keys dynamic-capability registrations; must be stable."""
    assert MarksmanLanguageServer.server_id == "marksman"


def test_get_language_enum_instance_returns_markdown() -> None:
    """Identity tie-back to ``Language.MARKDOWN`` (per Stage 1E pattern)."""
    assert MarksmanLanguageServer.get_language_enum_instance() == Language.MARKDOWN


def test_is_ignored_dirname_includes_obsidian_and_node_modules(tmp_path) -> None:
    """Obsidian / Vitepress vaults + node_modules dominate markdown trees."""
    if shutil.which("marksman") is None:
        pytest.skip("marksman not on PATH; skipping adapter instantiation")
    cfg = LanguageServerConfig(code_language=Language.MARKDOWN)
    srv = MarksmanLanguageServer(cfg, str(tmp_path), SolidLSPSettings())
    assert srv.is_ignored_dirname(".obsidian") is True
    assert srv.is_ignored_dirname("node_modules") is True
    assert srv.is_ignored_dirname(".git") is True
    # ``src`` is a normal directory and must not be ignored.
    assert srv.is_ignored_dirname("src") is False


def test_initialize_params_advertise_workspace_apply_edit(tmp_path) -> None:
    """``workspace.applyEdit=True`` is essential for cross-file rename writes."""
    # Cast through ``dict[str, Any]`` because the LSP TypedDicts mark every
    # capability key as NotRequired; the adapter's _get_initialize_params
    # always emits these keys, and this test asserts that contract.
    params = cast(dict[str, Any], MarksmanLanguageServer._get_initialize_params(str(tmp_path)))
    workspace_caps = params["capabilities"]["workspace"]
    assert workspace_caps["applyEdit"] is True
    # ``documentChanges`` lets us return resource ops (rename heading → file rename).
    assert workspace_caps["workspaceEdit"]["documentChanges"] is True


def test_initialize_params_advertise_rename_with_prepare(tmp_path) -> None:
    """``rename.prepareSupport=True`` lets clients show heading-rename UI."""
    params = cast(dict[str, Any], MarksmanLanguageServer._get_initialize_params(str(tmp_path)))
    text_doc_caps = params["capabilities"]["textDocument"]
    assert text_doc_caps["rename"]["prepareSupport"] is True
    # documentLink is essential for the organize_links facade (Leaf 02).
    assert "documentLink" in text_doc_caps
    # documentSymbol is essential for split_doc / extract_section facades.
    assert text_doc_caps["documentSymbol"]["hierarchicalDocumentSymbolSupport"] is True
