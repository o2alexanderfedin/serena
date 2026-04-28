"""Stream 6 / Leaf E — LeanServer adapter unit tests.

These tests are *unit* level: they exercise the adapter's constants and
small introspection methods without spawning a real ``lean --server``
subprocess. The end-to-end smoke (boot + initialize + documentSymbol
round-trip) lives in ``test/solidlsp/lean4/`` once ``lean`` is confirmed
on the host.

The adapter mirrors the ``JdtlsServer`` shape
(single-LSP-per-language, sync facade methods, ``server_id: ClassVar[str]``)
so this test suite is deliberately thin — the broader Stage 1A facade
contract is exercised by the multi-server tests once the strategy is
registered.

Key invariant tested here: the codeActionKind valueSet advertised to
``lean --server`` contains ONLY ``"quickfix"`` — no rename or extract
kinds — because Lean 4 is a dependent-type theorem prover where those
operations can silently invalidate proofs (see lean_server.py and
lean_strategy.py module docstrings for the full rationale).
"""

from __future__ import annotations

import shutil
from typing import Any, cast

import pytest

from solidlsp.language_servers.lean_server import LeanServer
from solidlsp.ls_config import Language, LanguageServerConfig
from solidlsp.settings import SolidLSPSettings


def test_server_id_constant_is_lean() -> None:
    """``server_id`` keys dynamic-capability registrations; must be stable."""
    assert LeanServer.server_id == "lean"


def test_get_language_enum_instance_returns_lean4() -> None:
    """Identity tie-back to ``Language.LEAN4`` (per Stage 1E pattern)."""
    assert LeanServer.get_language_enum_instance() == Language.LEAN4


def test_is_ignored_dirname_includes_lean_build_dirs(tmp_path) -> None:
    """.lake / build dominate Lean 4 project trees."""
    if shutil.which("lean") is None:
        pytest.skip("lean not on PATH; skipping adapter instantiation")
    cfg = LanguageServerConfig(code_language=Language.LEAN4)
    srv = LeanServer(cfg, str(tmp_path), SolidLSPSettings())
    assert srv.is_ignored_dirname(".lake") is True    # Lake build cache
    assert srv.is_ignored_dirname("build") is True    # Generic build output
    assert srv.is_ignored_dirname(".elan") is True    # elan toolchain cache
    # ``Mathlib`` is the main user-facing source library; must not be ignored.
    assert srv.is_ignored_dirname("Mathlib") is False
    # ``Std`` is the standard library; must not be ignored.
    assert srv.is_ignored_dirname("Std") is False
    # ``src`` is the conventional source directory.
    assert srv.is_ignored_dirname("src") is False


def test_initialize_params_advertise_workspace_apply_edit(tmp_path) -> None:
    """``workspace.applyEdit=True`` is essential for code-action edits."""
    params = cast(dict[str, Any], LeanServer._get_initialize_params(str(tmp_path)))
    workspace_caps = params["capabilities"]["workspace"]
    assert workspace_caps["applyEdit"] is True
    assert workspace_caps["workspaceEdit"]["documentChanges"] is True


def test_initialize_params_does_not_advertise_rename(tmp_path) -> None:
    """Lean 4 rename is UNSAFE for theorem provers — must NOT be advertised."""
    params = cast(dict[str, Any], LeanServer._get_initialize_params(str(tmp_path)))
    text_doc_caps = params["capabilities"]["textDocument"]
    # ``rename`` capability MUST NOT be present.
    assert "rename" not in text_doc_caps


def test_initialize_params_advertise_code_action_quickfix_only(tmp_path) -> None:
    """The codeActionKind valueSet MUST contain only 'quickfix'.

    This is the core safety invariant for a theorem prover: no rename,
    no extract, no refactor — only semantics-preserving quickfix suggestions.
    """
    params = cast(dict[str, Any], LeanServer._get_initialize_params(str(tmp_path)))
    kinds: list[str] = params["capabilities"]["textDocument"]["codeAction"][
        "codeActionLiteralSupport"
    ]["codeActionKind"]["valueSet"]
    assert kinds == ["quickfix"], (
        f"LeanServer must advertise ONLY 'quickfix' (got {kinds!r}); "
        f"see lean_server.py module docstring for the theorem-prover rationale."
    )


def test_initialize_params_advertise_definition_and_references(tmp_path) -> None:
    """Lean 4 supports go-to-definition and find-references."""
    params = cast(dict[str, Any], LeanServer._get_initialize_params(str(tmp_path)))
    text_doc_caps = params["capabilities"]["textDocument"]
    assert "definition" in text_doc_caps
    assert text_doc_caps["definition"]["linkSupport"] is True
    assert "references" in text_doc_caps


def test_initialize_params_advertise_hover(tmp_path) -> None:
    """Lean 4 hover is rich (shows type, docstring, tactic state)."""
    params = cast(dict[str, Any], LeanServer._get_initialize_params(str(tmp_path)))
    text_doc_caps = params["capabilities"]["textDocument"]
    assert "hover" in text_doc_caps
    assert "markdown" in text_doc_caps["hover"]["contentFormat"]


def test_initialize_params_advertise_document_symbol(tmp_path) -> None:
    """Document symbol support enables workspace-symbol crawl."""
    params = cast(dict[str, Any], LeanServer._get_initialize_params(str(tmp_path)))
    text_doc_caps = params["capabilities"]["textDocument"]
    assert "documentSymbol" in text_doc_caps
    assert text_doc_caps["documentSymbol"]["hierarchicalDocumentSymbolSupport"] is True


def test_initialize_params_has_process_id(tmp_path) -> None:
    """``processId`` must be an int (validates the static method is callable)."""
    params = cast(dict[str, Any], LeanServer._get_initialize_params(str(tmp_path)))
    assert "processId" in params
    assert isinstance(params["processId"], int)


def test_initialize_params_workspace_folders_present(tmp_path) -> None:
    """``workspaceFolders`` must be set so lean --server can locate Lake packages."""
    params = cast(dict[str, Any], LeanServer._get_initialize_params(str(tmp_path)))
    assert "workspaceFolders" in params
    assert len(params["workspaceFolders"]) == 1
    assert params["workspaceFolders"][0]["name"] == tmp_path.name
