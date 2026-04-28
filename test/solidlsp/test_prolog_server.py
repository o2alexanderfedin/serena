"""Stream 6 / Leaf G — PrologServer adapter unit tests.

Unit-level tests: exercise the adapter's constants and small introspection
methods without spawning a real ``swipl`` subprocess.

Key invariants tested:
  - ``server_id`` is stable (used for dynamic-capability registration).
  - ``get_language_enum_instance()`` returns ``Language.PROLOG``.
  - ``is_ignored_dirname`` excludes SWI-Prolog cache dirs.
  - Initialize-params advertise ``quickfix`` + ``refactor.rename``.
  - Initialize-params advertise the ``rename`` textDocument capability.
  - Workspace ``applyEdit=True`` is present.
  - No unsafe ``refactor.extract`` kind is advertised.
"""

from __future__ import annotations

import shutil
from typing import Any, cast

import pytest

from solidlsp.language_servers.prolog_server import PrologServer
from solidlsp.ls_config import Language


def test_server_id_constant() -> None:
    """``server_id`` must be 'swipl-lsp'."""
    assert PrologServer.server_id == "swipl-lsp"


def test_get_language_enum_instance_returns_prolog() -> None:
    """Identity tie-back to ``Language.PROLOG``."""
    assert PrologServer.get_language_enum_instance() == Language.PROLOG


def test_language_prolog_in_enum() -> None:
    """Language.PROLOG exists in the enum and has the right value."""
    assert Language.PROLOG.value == "prolog"


def test_initialize_params_advertise_workspace_apply_edit(tmp_path) -> None:
    """``workspace.applyEdit=True`` is required for code-action edits."""
    params = cast(dict[str, Any], PrologServer._get_initialize_params(str(tmp_path)))
    workspace_caps = params["capabilities"]["workspace"]
    assert workspace_caps["applyEdit"] is True
    assert workspace_caps["workspaceEdit"]["documentChanges"] is True


def test_initialize_params_advertise_rename_capability(tmp_path) -> None:
    """``textDocument.rename`` MUST be present — Prolog rename is alpha-safe."""
    params = cast(dict[str, Any], PrologServer._get_initialize_params(str(tmp_path)))
    text_doc_caps = params["capabilities"]["textDocument"]
    assert "rename" in text_doc_caps
    assert text_doc_caps["rename"]["prepareSupport"] is True


def test_initialize_params_advertise_quickfix_and_rename_kinds(tmp_path) -> None:
    """The codeActionKind valueSet MUST contain 'quickfix' and 'refactor.rename'.

    Prolog predicate renaming is a clean alpha-substitution (no dependent types,
    no proof context), so it is safe to advertise.
    """
    params = cast(dict[str, Any], PrologServer._get_initialize_params(str(tmp_path)))
    kinds: list[str] = params["capabilities"]["textDocument"]["codeAction"][
        "codeActionLiteralSupport"
    ]["codeActionKind"]["valueSet"]
    assert "quickfix" in kinds, "quickfix must be advertised"
    assert "refactor.rename" in kinds, "refactor.rename must be advertised (alpha-safe)"


def test_initialize_params_does_not_advertise_extract(tmp_path) -> None:
    """``refactor.extract`` MUST NOT be advertised — goal extraction requires
    binding-context analysis that the current lsp_server pack does not provide.
    """
    params = cast(dict[str, Any], PrologServer._get_initialize_params(str(tmp_path)))
    kinds: list[str] = params["capabilities"]["textDocument"]["codeAction"][
        "codeActionLiteralSupport"
    ]["codeActionKind"]["valueSet"]
    extract_kinds = [k for k in kinds if "extract" in k]
    assert extract_kinds == [], (
        f"PrologServer must NOT advertise extract kinds (got {extract_kinds!r})"
    )


def test_initialize_params_advertise_definition_and_references(tmp_path) -> None:
    """Prolog LSP supports go-to-definition and find-references."""
    params = cast(dict[str, Any], PrologServer._get_initialize_params(str(tmp_path)))
    text_doc_caps = params["capabilities"]["textDocument"]
    assert "definition" in text_doc_caps
    assert text_doc_caps["definition"]["linkSupport"] is True
    assert "references" in text_doc_caps


def test_initialize_params_advertise_hover(tmp_path) -> None:
    """Hover shows predicate documentation from the lsp_server pack."""
    params = cast(dict[str, Any], PrologServer._get_initialize_params(str(tmp_path)))
    text_doc_caps = params["capabilities"]["textDocument"]
    assert "hover" in text_doc_caps
    assert "markdown" in text_doc_caps["hover"]["contentFormat"]


def test_initialize_params_has_process_id(tmp_path) -> None:
    """``processId`` must be an int."""
    params = cast(dict[str, Any], PrologServer._get_initialize_params(str(tmp_path)))
    assert "processId" in params
    assert isinstance(params["processId"], int)


def test_initialize_params_workspace_folders_present(tmp_path) -> None:
    """``workspaceFolders`` must be set for project-root detection."""
    params = cast(dict[str, Any], PrologServer._get_initialize_params(str(tmp_path)))
    assert "workspaceFolders" in params
    assert len(params["workspaceFolders"]) == 1
    assert params["workspaceFolders"][0]["name"] == tmp_path.name


def test_is_ignored_dirname_excludes_swipl_cache(tmp_path) -> None:
    """SWI-Prolog runtime/pack cache dirs should be skipped."""
    from solidlsp.ls_config import Language, LanguageServerConfig
    from solidlsp.settings import SolidLSPSettings

    if shutil.which("swipl") is None:
        pytest.skip("swipl not on PATH; skipping adapter instantiation")
    cfg = LanguageServerConfig(code_language=Language.PROLOG)
    srv = PrologServer(cfg, str(tmp_path), SolidLSPSettings())
    assert srv.is_ignored_dirname(".swipl") is True
    assert srv.is_ignored_dirname("pack") is True
    assert srv.is_ignored_dirname("src") is False
    assert srv.is_ignored_dirname("tests") is False


def test_language_prolog_filename_matcher() -> None:
    """Language.PROLOG must match .pl, .pro, .prolog extensions."""
    matcher = Language.PROLOG.get_source_fn_matcher()
    assert matcher.is_relevant_filename("main.pl") is True
    assert matcher.is_relevant_filename("app.pro") is True
    assert matcher.is_relevant_filename("rules.prolog") is True
    assert matcher.is_relevant_filename("main.py") is False
    assert matcher.is_relevant_filename("main.lean") is False


def test_prolog_installer_detect_and_install() -> None:
    """PrologInstaller.detect_installed works; if swipl absent, present=False."""
    from serena.installer.prolog_installer import PrologInstaller

    installer = PrologInstaller()
    status = installer.detect_installed()
    if shutil.which("swipl") is None:
        assert status.present is False
    else:
        # swipl found; present depends on whether lsp_server pack is installed
        assert isinstance(status.present, bool)

    # latest_available always returns None (no API)
    assert installer.latest_available() is None


def test_prolog_installer_install_command_requires_swipl() -> None:
    """If swipl is absent, _install_command raises NotImplementedError."""
    from serena.installer.prolog_installer import PrologInstaller

    installer = PrologInstaller()
    if shutil.which("swipl") is None:
        with pytest.raises(NotImplementedError) as exc_info:
            installer._install_command()
        assert "SWI-Prolog" in str(exc_info.value) or "swipl" in str(exc_info.value)
    else:
        # swipl present — command should be a valid tuple starting with the binary
        cmd = installer._install_command()
        assert isinstance(cmd, tuple)
        assert len(cmd) > 0
        assert "swipl" in cmd[0]
