"""Stream 6 / Leaf H — ProblogServer adapter unit tests.

Unit-level tests: exercise the adapter's constants and small introspection
methods without spawning a real ``swipl`` subprocess.

Key invariants tested:
  - ``server_id`` is stable (used for dynamic-capability registration).
  - ``get_language_enum_instance()`` returns ``Language.PROBLOG``.
  - ``is_ignored_dirname`` excludes swipl cache and Python cache dirs.
  - Initialize-params advertise ONLY ``quickfix`` (research-mode language).
  - Initialize-params do NOT advertise ``rename`` (probabilistic rename is
    research-mode — see problog_server.py module docstring).
  - Workspace ``applyEdit=True`` is present.
"""

from __future__ import annotations

import shutil
from typing import Any, cast

import pytest

from solidlsp.language_servers.problog_server import ProblogServer
from solidlsp.ls_config import Language


def test_server_id_constant() -> None:
    """``server_id`` must be 'problog-lsp'."""
    assert ProblogServer.server_id == "problog-lsp"


def test_get_language_enum_instance_returns_problog() -> None:
    """Identity tie-back to ``Language.PROBLOG``."""
    assert ProblogServer.get_language_enum_instance() == Language.PROBLOG


def test_language_problog_in_enum() -> None:
    """Language.PROBLOG exists in the enum and has the right value."""
    assert Language.PROBLOG.value == "problog"


def test_initialize_params_advertise_workspace_apply_edit(tmp_path) -> None:
    """``workspace.applyEdit=True`` is required for code-action edits."""
    params = cast(dict[str, Any], ProblogServer._get_initialize_params(str(tmp_path)))
    workspace_caps = params["capabilities"]["workspace"]
    assert workspace_caps["applyEdit"] is True
    assert workspace_caps["workspaceEdit"]["documentChanges"] is True


def test_initialize_params_does_not_advertise_rename(tmp_path) -> None:
    """ProbLog rename is research-mode — ``textDocument.rename`` must NOT be present.

    Renaming a probabilistic fact must update EM-learning weights and other
    cross-cutting concerns that the Prolog LSP backend is unaware of.
    """
    params = cast(dict[str, Any], ProblogServer._get_initialize_params(str(tmp_path)))
    text_doc_caps = params["capabilities"]["textDocument"]
    assert "rename" not in text_doc_caps


def test_initialize_params_advertise_code_action_quickfix_only(tmp_path) -> None:
    """The codeActionKind valueSet MUST contain only 'quickfix'.

    ProbLog's probabilistic semantics make rename/extract research-mode.
    Only syntax-level quickfix is safe.
    """
    params = cast(dict[str, Any], ProblogServer._get_initialize_params(str(tmp_path)))
    kinds: list[str] = params["capabilities"]["textDocument"]["codeAction"][
        "codeActionLiteralSupport"
    ]["codeActionKind"]["valueSet"]
    assert kinds == ["quickfix"], (
        f"ProblogServer must advertise ONLY 'quickfix' (got {kinds!r}); "
        f"see problog_server.py module docstring for the probabilistic-semantics rationale."
    )


def test_initialize_params_advertise_definition_and_references(tmp_path) -> None:
    """ProbLog supports go-to-definition and find-references (Prolog subset)."""
    params = cast(dict[str, Any], ProblogServer._get_initialize_params(str(tmp_path)))
    text_doc_caps = params["capabilities"]["textDocument"]
    assert "definition" in text_doc_caps
    assert text_doc_caps["definition"]["linkSupport"] is True
    assert "references" in text_doc_caps


def test_initialize_params_advertise_hover(tmp_path) -> None:
    """Hover shows predicate documentation for the Prolog subset."""
    params = cast(dict[str, Any], ProblogServer._get_initialize_params(str(tmp_path)))
    text_doc_caps = params["capabilities"]["textDocument"]
    assert "hover" in text_doc_caps
    assert "markdown" in text_doc_caps["hover"]["contentFormat"]


def test_initialize_params_has_process_id(tmp_path) -> None:
    """``processId`` must be an int."""
    params = cast(dict[str, Any], ProblogServer._get_initialize_params(str(tmp_path)))
    assert "processId" in params
    assert isinstance(params["processId"], int)


def test_initialize_params_workspace_folders_present(tmp_path) -> None:
    """``workspaceFolders`` must be set."""
    params = cast(dict[str, Any], ProblogServer._get_initialize_params(str(tmp_path)))
    assert "workspaceFolders" in params
    assert len(params["workspaceFolders"]) == 1
    assert params["workspaceFolders"][0]["name"] == tmp_path.name


def test_is_ignored_dirname_excludes_cache_dirs(tmp_path) -> None:
    """swipl and Python cache dirs should be ignored."""
    from solidlsp.ls_config import Language, LanguageServerConfig
    from solidlsp.settings import SolidLSPSettings

    if shutil.which("swipl") is None:
        pytest.skip("swipl not on PATH; skipping adapter instantiation")
    cfg = LanguageServerConfig(code_language=Language.PROBLOG)
    srv = ProblogServer(cfg, str(tmp_path), SolidLSPSettings())
    assert srv.is_ignored_dirname(".swipl") is True
    assert srv.is_ignored_dirname("__pycache__") is True
    assert srv.is_ignored_dirname("src") is False
    assert srv.is_ignored_dirname("tests") is False


def test_language_problog_filename_matcher() -> None:
    """Language.PROBLOG must match .problog extension only."""
    matcher = Language.PROBLOG.get_source_fn_matcher()
    assert matcher.is_relevant_filename("model.problog") is True
    assert matcher.is_relevant_filename("main.pl") is False
    assert matcher.is_relevant_filename("main.py") is False
    assert matcher.is_relevant_filename("model.lean") is False


def test_problog_installer_install_command() -> None:
    """ProblogInstaller._install_command returns a pip install tuple."""
    from serena.installer.problog_installer import ProblogInstaller

    installer = ProblogInstaller()
    cmd = installer._install_command()
    assert isinstance(cmd, tuple)
    assert "pip" in " ".join(cmd) or "problog" in cmd[-1]


def test_problog_installer_latest_available_returns_none() -> None:
    """ProblogInstaller.latest_available returns None (no release channel API)."""
    from serena.installer.problog_installer import ProblogInstaller

    installer = ProblogInstaller()
    assert installer.latest_available() is None


def test_problog_installer_detect_installed() -> None:
    """ProblogInstaller.detect_installed runs without error."""
    from serena.installer.problog_installer import ProblogInstaller

    installer = ProblogInstaller()
    status = installer.detect_installed()
    # Whatever the host state, detect_installed must not raise.
    assert isinstance(status.present, bool)
