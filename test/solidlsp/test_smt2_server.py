"""Stream 6 / Leaf F — Smt2Server adapter unit tests (v1.4.1: dolmenls-backed).

Unit-level tests: exercise the adapter's constants and small introspection
methods without spawning a real ``dolmenls`` subprocess.

Key invariants tested:
  - ``server_id == "dolmenls"`` — keys dynamic-capability registrations.
  - ``get_language_enum_instance()`` returns ``Language.SMT2``.
  - ``is_ignored_dirname`` excludes solver temp dirs (.z3, .cvc5).
  - Initialize-params advertise ONLY ``quickfix`` — SMT-LIB 2 is a constraint
    format; rename/extract have no solver-level semantics.
  - Workspace ``applyEdit=True`` is present (needed for code-action edits).
  - ``rename`` capability is NOT in textDocument (no SMT2 rename semantics).
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from solidlsp.language_servers.smt2_server import Smt2Server
from solidlsp.ls_config import Language


def test_server_id_constant() -> None:
    """``server_id`` keys dynamic-capability registrations; must be stable.

    v1.4.1: renamed from ``smt2-lsp`` (sentinel) to ``dolmenls`` (real binary).
    """
    assert Smt2Server.server_id == "dolmenls"


def test_get_language_enum_instance_returns_smt2() -> None:
    """Identity tie-back to ``Language.SMT2``."""
    assert Smt2Server.get_language_enum_instance() == Language.SMT2


def test_language_smt2_in_enum() -> None:
    """Language.SMT2 exists in the enum and has the right value."""
    assert Language.SMT2.value == "smt2"


def test_initialize_params_advertise_workspace_apply_edit(tmp_path) -> None:
    """``workspace.applyEdit=True`` is required for code-action edits."""
    params = cast(dict[str, Any], Smt2Server._get_initialize_params(str(tmp_path)))
    workspace_caps = params["capabilities"]["workspace"]
    assert workspace_caps["applyEdit"] is True
    assert workspace_caps["workspaceEdit"]["documentChanges"] is True


def test_initialize_params_does_not_advertise_rename(tmp_path) -> None:
    """SMT-LIB 2 has no rename semantics at the solver level — must NOT be advertised."""
    params = cast(dict[str, Any], Smt2Server._get_initialize_params(str(tmp_path)))
    text_doc_caps = params["capabilities"]["textDocument"]
    assert "rename" not in text_doc_caps


def test_initialize_params_advertise_code_action_quickfix_only(tmp_path) -> None:
    """The codeActionKind valueSet MUST contain only 'quickfix'.

    SMT-LIB 2 is a constraint format; rename/extract have no solver-level
    semantics and are therefore excluded from the allow-list.
    """
    params = cast(dict[str, Any], Smt2Server._get_initialize_params(str(tmp_path)))
    kinds: list[str] = params["capabilities"]["textDocument"]["codeAction"][
        "codeActionLiteralSupport"
    ]["codeActionKind"]["valueSet"]
    assert kinds == ["quickfix"], (
        f"Smt2Server must advertise ONLY 'quickfix' (got {kinds!r}); "
        f"see smt2_server.py module docstring for the constraint-format rationale."
    )


def test_initialize_params_advertise_definition_and_references(tmp_path) -> None:
    """SMT-LIB 2 supports go-to-definition and find-references (for future LSP)."""
    params = cast(dict[str, Any], Smt2Server._get_initialize_params(str(tmp_path)))
    text_doc_caps = params["capabilities"]["textDocument"]
    assert "definition" in text_doc_caps
    assert text_doc_caps["definition"]["linkSupport"] is True
    assert "references" in text_doc_caps


def test_initialize_params_advertise_hover(tmp_path) -> None:
    """Hover support (type info from solver feedback)."""
    params = cast(dict[str, Any], Smt2Server._get_initialize_params(str(tmp_path)))
    text_doc_caps = params["capabilities"]["textDocument"]
    assert "hover" in text_doc_caps
    assert "markdown" in text_doc_caps["hover"]["contentFormat"]


def test_initialize_params_has_process_id(tmp_path) -> None:
    """``processId`` must be an int."""
    params = cast(dict[str, Any], Smt2Server._get_initialize_params(str(tmp_path)))
    assert "processId" in params
    assert isinstance(params["processId"], int)


def test_initialize_params_workspace_folders_present(tmp_path) -> None:
    """``workspaceFolders`` must be set for multi-file SMT2 benchmark suites."""
    params = cast(dict[str, Any], Smt2Server._get_initialize_params(str(tmp_path)))
    assert "workspaceFolders" in params
    assert len(params["workspaceFolders"]) == 1
    assert params["workspaceFolders"][0]["name"] == tmp_path.name


def test_is_ignored_dirname_excludes_solver_temp_dirs(tmp_path) -> None:
    """Solver temp/cache dirs should be ignored during workspace crawl."""
    from solidlsp.ls_config import Language, LanguageServerConfig
    from solidlsp.settings import SolidLSPSettings

    cfg = LanguageServerConfig(code_language=Language.SMT2)
    srv = Smt2Server(cfg, str(tmp_path), SolidLSPSettings())
    assert srv.is_ignored_dirname(".z3") is True     # Z3 temp/cache
    assert srv.is_ignored_dirname(".cvc5") is True   # CVC5 temp/cache
    assert srv.is_ignored_dirname("benchmarks") is False
    assert srv.is_ignored_dirname("examples") is False
    assert srv.is_ignored_dirname("src") is False


def test_language_smt2_filename_matcher() -> None:
    """Language.SMT2 must match .smt2 and .smt extensions."""
    matcher = Language.SMT2.get_source_fn_matcher()
    assert matcher.is_relevant_filename("query.smt2") is True
    assert matcher.is_relevant_filename("benchmark.smt") is True
    assert matcher.is_relevant_filename("query.lean") is False
    assert matcher.is_relevant_filename("main.py") is False


def test_smt2_installer_raises_not_implemented() -> None:
    """Smt2Installer._install_command raises NotImplementedError (no LSP exists)."""
    from serena.installer.smt2_installer import Smt2Installer

    installer = Smt2Installer()
    with pytest.raises(NotImplementedError) as exc_info:
        installer._install_command()
    msg = str(exc_info.value)
    assert "SMT-LIB 2" in msg or "SMT" in msg


def test_smt2_installer_detect_installed_returns_not_present() -> None:
    """Smt2Installer.detect_installed always returns present=False."""
    from serena.installer.smt2_installer import Smt2Installer

    installer = Smt2Installer()
    status = installer.detect_installed()
    assert status.present is False


def test_smt2_installer_latest_available_returns_none() -> None:
    """Smt2Installer.latest_available returns None (no release channel)."""
    from serena.installer.smt2_installer import Smt2Installer

    installer = Smt2Installer()
    assert installer.latest_available() is None
