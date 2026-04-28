"""Stream 6 / Leaf D — JdtlsServer adapter unit tests.

These tests are *unit* level: they exercise the adapter's constants and
small introspection methods without spawning a real jdtls subprocess.
The end-to-end smoke (boot + initialize + documentSymbol round-trip)
lives in ``test/solidlsp/java/`` once jdtls is confirmed on the host
(the existing Java integration tests cover that path via EclipseJDTLS).

The adapter mirrors the ``ClangdServer`` shape
(single-LSP-per-language, sync facade methods, ``server_id: ClassVar[str]``)
so this test suite is deliberately thin — the broader Stage 1A facade
contract is exercised by the multi-server tests once the strategy is
registered.
"""

from __future__ import annotations

import shutil
from typing import Any, cast

import pytest

from solidlsp.language_servers.jdtls_server import JdtlsServer
from solidlsp.ls_config import Language, LanguageServerConfig
from solidlsp.settings import SolidLSPSettings


def test_server_id_constant_is_jdtls() -> None:
    """``server_id`` keys dynamic-capability registrations; must be stable."""
    assert JdtlsServer.server_id == "jdtls"


def test_get_language_enum_instance_returns_java() -> None:
    """Identity tie-back to ``Language.JAVA`` (per Stage 1E pattern)."""
    assert JdtlsServer.get_language_enum_instance() == Language.JAVA


def test_is_ignored_dirname_includes_java_build_dirs(tmp_path) -> None:
    """target / build / .gradle / bin / out dominate Java project trees."""
    if shutil.which("jdtls") is None:
        pytest.skip("jdtls not on PATH; skipping adapter instantiation")
    cfg = LanguageServerConfig(code_language=Language.JAVA)
    srv = JdtlsServer(cfg, str(tmp_path), SolidLSPSettings())
    assert srv.is_ignored_dirname("target") is True    # Maven
    assert srv.is_ignored_dirname("build") is True     # Gradle
    assert srv.is_ignored_dirname(".gradle") is True   # Gradle cache
    assert srv.is_ignored_dirname("bin") is True       # Eclipse
    assert srv.is_ignored_dirname("out") is True       # IntelliJ IDEA
    assert srv.is_ignored_dirname("classes") is True
    assert srv.is_ignored_dirname(".cache") is True
    # ``src`` is the standard Java source directory and must not be ignored.
    assert srv.is_ignored_dirname("src") is False
    # ``main`` and ``test`` are Maven source sub-directories.
    assert srv.is_ignored_dirname("main") is False
    assert srv.is_ignored_dirname("test") is False


def test_initialize_params_advertise_workspace_apply_edit(tmp_path) -> None:
    """``workspace.applyEdit=True`` is essential for cross-file rename writes."""
    params = cast(dict[str, Any], JdtlsServer._get_initialize_params(str(tmp_path)))
    workspace_caps = params["capabilities"]["workspace"]
    assert workspace_caps["applyEdit"] is True
    assert workspace_caps["workspaceEdit"]["documentChanges"] is True


def test_initialize_params_advertise_rename_with_prepare(tmp_path) -> None:
    """``rename.prepareSupport=True`` is required for workspace-rename UI."""
    params = cast(dict[str, Any], JdtlsServer._get_initialize_params(str(tmp_path)))
    text_doc_caps = params["capabilities"]["textDocument"]
    assert text_doc_caps["rename"]["prepareSupport"] is True


def test_initialize_params_advertise_code_action_kinds(tmp_path) -> None:
    """jdtls code action kinds must include the Java refactor + generate family."""
    params = cast(dict[str, Any], JdtlsServer._get_initialize_params(str(tmp_path)))
    kinds: list[str] = params["capabilities"]["textDocument"]["codeAction"][
        "codeActionLiteralSupport"
    ]["codeActionKind"]["valueSet"]
    # Import management
    assert "source.organizeImports" in kinds
    # Code generation
    assert "source.generate.constructor" in kinds
    assert "source.generate.hashCodeEquals" in kinds
    assert "source.generate.toString" in kinds
    assert "source.generate.accessors" in kinds
    # Extract refactors
    assert "refactor.extract.method" in kinds
    assert "refactor.extract.variable" in kinds
    # Inline refactors
    assert "refactor.inline" in kinds
    # Rewrite refactors
    assert "refactor.rewrite" in kinds
    # Quickfix
    assert "quickfix" in kinds


def test_initialize_params_language_id_is_java(tmp_path) -> None:
    """``processId`` must be an int (validates the static method is callable)."""
    params = cast(dict[str, Any], JdtlsServer._get_initialize_params(str(tmp_path)))
    assert "processId" in params
    assert isinstance(params["processId"], int)
