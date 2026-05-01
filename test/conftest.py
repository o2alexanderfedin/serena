import logging
import os
import platform
import shutil as _sh
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from _pytest.mark import Mark, MarkDecorator
from sensai.util.logging import configure

from serena.config.serena_config import SerenaConfig, SerenaPaths
from serena.constants import SERENA_MANAGED_DIR_NAME
from serena.project import Project
from serena.util.file_system import GitignoreParser
from solidlsp.ls import SolidLanguageServer
from solidlsp.ls_config import Language, LanguageServerConfig
from solidlsp.ls_exceptions import SolidLSPException
from solidlsp.settings import SolidLSPSettings

from .solidlsp.clojure import is_clojure_cli_available

configure(level=logging.INFO)

log = logging.getLogger(__name__)


# Auto-load the opt-in developer-host plugin. It is a no-op unless
# ``O2_SCALPEL_LOCAL_HOST=1`` is set, so CI inherits a clean
# environment. See ``docs/dev/host-rustc-shim.md``.
pytest_plugins = ["test.conftest_dev_host"]


@pytest.fixture(scope="session")
def resources_dir() -> Path:
    """Path to the test resources directory."""
    current_dir = Path(__file__).parent
    return current_dir / "resources"


class LanguageParamRequest:
    param: Language


_LANGUAGE_REPO_ALIASES: dict[Language, Language] = {
    Language.CPP_CCLS: Language.CPP,
    Language.PHP_PHPACTOR: Language.PHP,
    Language.PYTHON_JEDI: Language.PYTHON,
    Language.RUBY_SOLARGRAPH: Language.RUBY,
    Language.PYTHON_TY: Language.PYTHON,
}


def get_repo_path(language: Language) -> Path:
    repo_language = _LANGUAGE_REPO_ALIASES.get(language, language)
    return Path(__file__).parent / "resources" / "repos" / repo_language / "test_repo"


def _create_ls(
    language: Language,
    repo_path: str | None = None,
    ignored_paths: list[str] | None = None,
    trace_lsp_communication: bool = False,
    ls_specific_settings: dict[Language, dict[str, Any]] | None = None,
    solidlsp_dir: Path | None = None,
) -> SolidLanguageServer:
    ignored_paths = ignored_paths or []
    if repo_path is None:
        repo_path = str(get_repo_path(language))
    gitignore_parser = GitignoreParser(str(repo_path))
    for spec in gitignore_parser.get_ignore_specs():
        ignored_paths.extend(spec.patterns)
    config = LanguageServerConfig(
        code_language=language,
        ignored_paths=ignored_paths,
        trace_lsp_communication=trace_lsp_communication,
    )
    effective_solidlsp_dir = solidlsp_dir if solidlsp_dir is not None else SerenaPaths().serena_user_home_dir
    project_data_path = os.path.join(repo_path, SERENA_MANAGED_DIR_NAME)
    return SolidLanguageServer.create(
        config,
        repo_path,
        solidlsp_settings=SolidLSPSettings(
            solidlsp_dir=effective_solidlsp_dir,
            project_data_path=project_data_path,
            ls_specific_settings=ls_specific_settings or {},
        ),
    )


@contextmanager
def start_ls_context(
    language: Language,
    repo_path: str | None = None,
    ignored_paths: list[str] | None = None,
    trace_lsp_communication: bool = False,
    ls_specific_settings: dict[Language, dict[str, Any]] | None = None,
    solidlsp_dir: Path | None = None,
) -> Iterator[SolidLanguageServer]:
    ls = _create_ls(language, repo_path, ignored_paths, trace_lsp_communication, ls_specific_settings, solidlsp_dir)
    log.info(f"Starting language server for {language} {repo_path}")
    ls.start()
    try:
        log.info(f"Language server started for {language} {repo_path}")
        yield ls
    finally:
        log.info(f"Stopping language server for {language} {repo_path}")
        try:
            ls.stop(shutdown_timeout=5)
        except Exception as e:
            log.warning(f"Warning: Error stopping language server: {e}")
            # try to force cleanup
            if hasattr(ls, "server") and hasattr(ls.server, "process"):
                try:
                    ls.server.process.terminate()
                except:
                    pass


@contextmanager
def start_default_ls_context(language: Language) -> Iterator[SolidLanguageServer]:
    with start_ls_context(language) as ls:
        yield ls


def create_default_serena_config():
    return SerenaConfig(gui_log_window=False, web_dashboard=False)


def _create_default_project(language: Language, repo_root_override: str | None = None) -> Project:
    repo_path = str(get_repo_path(language)) if repo_root_override is None else repo_root_override
    return Project.load(repo_path, serena_config=create_default_serena_config())


@pytest.fixture(scope="session")
def repo_path(request: LanguageParamRequest) -> Path:
    """Get the repository path for a specific language.

    This fixture requires a language parameter via pytest.mark.parametrize:

    Example:
    ```
    @pytest.mark.parametrize("repo_path", [Language.PYTHON], indirect=True)
    def test_python_repo(repo_path):
        assert (repo_path / "src").exists()
    ```

    """
    if not hasattr(request, "param"):
        raise ValueError("Language parameter must be provided via pytest.mark.parametrize")

    language = request.param
    return get_repo_path(language)


# Setup-time error message needles raised by individual language-server adapters
# when the host LSP binary (or its installer toolchain) is missing. When any of
# these substrings appears in a RuntimeError or FileNotFoundError raised while
# constructing/starting the LS, the fixture converts the error into pytest.skip
# so the suite reports an honest skip outcome instead of a setup ERROR. Real
# bugs (errors whose messages don't match any of these phrasings) are re-raised
# untouched.
_LSP_BINARY_MISSING_NEEDLES: tuple[str, ...] = (
    "not installed",
    "not in PATH",
    "Failed to install",
    "is required",
    "Failed to find",
    "executable",
    "not found at",
    "Perl::LanguageServer is not installed",
    "Erlang LS not found",
)


# Setup-time error needles raised by SolidLSPException (i.e. the LSP started but
# refused the test session due to an upstream-host limitation, not a missing
# binary). These are surfaced as honest skips so the suite reports a clean
# outcome instead of an ERROR. Real bugs (messages that don't match) re-raise.
_LSP_HOST_LIMITATION_NEEDLES: tuple[str, ...] = (
    "Multiple editing sessions",
    # JetBrains kotlin-lsp surfaces its multi-session refusal as LSP error -32800
    # (RequestCancelled) on the initialize request — same root cause as the
    # "Multiple editing sessions" phrasing reported in upstream issues, but the
    # client only sees the cancellation code, not the human-readable text.
    "cancelled (-32800)",
)


def _maybe_skip_for_lsp_host_gap(exc: BaseException) -> None:
    """If ``exc`` is a known LSP-host-gap setup failure, convert it to ``pytest.skip``.

    Catches the same patterns as the ``language_server`` fixture but during
    *any* fixture setup (e.g. ``ls_with_ignored_dirs`` in
    ``test_erlang_ignored_dirs.py``) so the suite converts host-binary gaps
    into honest skips regardless of which fixture raised. Real bugs (messages
    that don't match any needle) are left to propagate untouched.
    """
    message = str(exc)
    if isinstance(exc, SolidLSPException):
        if any(needle in message for needle in _LSP_HOST_LIMITATION_NEEDLES):
            pytest.skip(f"LSP host limitation: {exc}")
        return
    if isinstance(exc, (RuntimeError, FileNotFoundError)):
        if any(needle in message for needle in _LSP_BINARY_MISSING_NEEDLES):
            pytest.skip(f"LSP binary not available: {exc}")


@pytest.hookimpl(hookwrapper=True)
def pytest_fixture_setup(fixturedef: Any, request: Any) -> Generator[None, None, None]:
    """Convert known LSP-host-gap fixture setup failures to skips.

    Pytest's ``pytest_fixture_setup`` hookwrapper sees the fixture's outcome
    after it runs. If the fixture raised a RuntimeError/FileNotFoundError
    matching ``_LSP_BINARY_MISSING_NEEDLES`` or a SolidLSPException matching
    ``_LSP_HOST_LIMITATION_NEEDLES``, we re-raise as ``pytest.skip`` so the
    test reports an honest skip outcome instead of a setup ERROR. Other
    exceptions propagate untouched, preserving normal failure reporting.
    """
    outcome = yield
    try:
        outcome.get_result()
    except (RuntimeError, FileNotFoundError, SolidLSPException) as exc:
        _maybe_skip_for_lsp_host_gap(exc)
        raise


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item: Any) -> Generator[None, None, None]:
    """Catch cached LSP-host-gap fixture failures replayed during test setup.

    When a module-scoped fixture (e.g. ``ls_with_ignored_dirs``) raises during
    its first instantiation, pytest caches the exception and re-raises it for
    every subsequent test that requests the same fixture — bypassing the
    ``pytest_fixture_setup`` hookwrapper. Without this safety net, the first
    test in the module reports an honest skip, but the rest report ERROR.
    This wrapper re-checks the same needle lists at runtest-setup time so all
    tests in the module skip uniformly. Real bugs (messages that don't match)
    propagate untouched.
    """
    outcome = yield
    try:
        outcome.get_result()
    except (RuntimeError, FileNotFoundError, SolidLSPException) as exc:
        _maybe_skip_for_lsp_host_gap(exc)
        raise


# Note: using module scope here to avoid restarting LS for each test function but still terminate between test modules
@pytest.fixture(scope="module")
def language_server(request: LanguageParamRequest):
    """Create a language server instance configured for the specified language.

    This fixture requires a language parameter via pytest.mark.parametrize:

    Example:
    ```
    @pytest.mark.parametrize("language_server", [Language.PYTHON], indirect=True)
    def test_python_server(language_server: SyncLanguageServer) -> None:
        # Use the Python language server
        pass
    ```

    You can also test multiple languages in a single test:
    ```
    @pytest.mark.parametrize("language_server", [Language.PYTHON, Language.TYPESCRIPT], indirect=True)
    def test_multiple_languages(language_server: SyncLanguageServer) -> None:
        # This test will run once for each language
        pass
    ```

    """
    if not hasattr(request, "param"):
        raise ValueError("Language parameter must be provided via pytest.mark.parametrize")

    language = request.param
    cm = start_default_ls_context(language)
    try:
        ls = cm.__enter__()
    except (RuntimeError, FileNotFoundError, SolidLSPException) as exc:
        message = str(exc)
        if isinstance(exc, SolidLSPException):
            if any(needle in message for needle in _LSP_HOST_LIMITATION_NEEDLES):
                pytest.skip(f"LSP host limitation: {exc}")
            raise
        if any(needle in message for needle in _LSP_BINARY_MISSING_NEEDLES):
            pytest.skip(f"LSP binary not available for {language.value}: {exc}")
        raise
    try:
        yield ls
    finally:
        # Re-enter the context manager's exit path so SolidLanguageServer.stop()
        # is called exactly once, matching the original ``with`` semantics. We
        # intentionally swallow any exit-time exception class via ``False`` —
        # the original ``with`` block did not suppress, but ``start_ls_context``
        # already wraps stop() in its own try/except, so this is equivalent.
        cm.__exit__(None, None, None)


@contextmanager
def project_context(language: Language, repo_root_override: str | None = None) -> Iterator[Project]:
    """Context manager that creates a Project for the specified language and ensures proper cleanup."""
    project = _create_default_project(language, repo_root_override)
    try:
        yield project
    finally:
        project.shutdown(timeout=5)


@pytest.fixture(scope="module")
def project(request: LanguageParamRequest, repo_root_override: str | None = None) -> Iterator[Project]:
    """Create a Project for the specified language.

    This fixture requires a language parameter via pytest.mark.parametrize:

    Example:
    ```
    @pytest.mark.parametrize("project", [Language.PYTHON], indirect=True)
    def test_python_project(project: Project) -> None:
        # Use the Python project to test something
        pass
    ```

    You can also test multiple languages in a single test:
    ```
    @pytest.mark.parametrize("project", [Language.PYTHON, Language.TYPESCRIPT], indirect=True)
    def test_multiple_languages(project: SyncLanguageServer) -> None:
        # This test will run once for each language
        pass
    ```

    """
    if not hasattr(request, "param"):
        raise ValueError("Language parameter must be provided via pytest.mark.parametrize")
    language = request.param
    with project_context(language, repo_root_override) as project:
        yield project


@contextmanager
def project_with_ls_context(language: Language, repo_root_override: str | None = None) -> Iterator[Project]:
    """Context manager that creates a Project with an active language server for the specified language."""
    with project_context(language, repo_root_override) as project:
        project.create_language_server_manager()
        yield project


@pytest.fixture(scope="module")
def project_with_ls(request: LanguageParamRequest) -> Iterator[Project]:
    if not hasattr(request, "param"):
        raise ValueError("Language parameter must be provided via pytest.mark.parametrize")
    language = request.param
    with project_with_ls_context(language) as project:
        yield project


is_ci = os.getenv("CI") == "true" or os.getenv("GITHUB_ACTIONS") == "true"
"""
Flag indicating whether the tests are running in the GitHub CI environment.
"""

is_windows = platform.system() == "Windows"


_LANGUAGE_PYTEST_MARKERS: dict[Language, list[MarkDecorator | Mark]] = {
    Language.CLOJURE: [
        pytest.mark.clojure,
        pytest.mark.skipif(not is_clojure_cli_available(), reason="clojure CLI is not installed"),
    ],
    Language.CPP: [pytest.mark.cpp],
    Language.CPP_CCLS: [pytest.mark.cpp],
    Language.CSHARP: [pytest.mark.csharp],
    Language.FSHARP: [pytest.mark.fsharp],
    Language.GO: [pytest.mark.go],
    Language.HAXE: [pytest.mark.haxe],
    Language.JAVA: [pytest.mark.java],
    Language.KOTLIN: [pytest.mark.kotlin, pytest.mark.skipif(is_ci, reason="Kotlin LSP JVM crashes on restart in CI")],
    Language.LEAN4: [pytest.mark.lean4, pytest.mark.skipif(_sh.which("lean") is None, reason="Lean is not installed")],
    Language.MSL: [pytest.mark.msl],
    Language.PHP: [pytest.mark.php],
    Language.PHP_PHPACTOR: [pytest.mark.php],
    Language.POWERSHELL: [pytest.mark.powershell],
    Language.PYTHON: [pytest.mark.python],
    Language.PYTHON_JEDI: [pytest.mark.python],
    Language.PYTHON_TY: [pytest.mark.python],
    Language.RUST: [pytest.mark.rust],
    Language.TYPESCRIPT: [pytest.mark.typescript],
}


def get_pytest_markers(language: Language) -> list[MarkDecorator | Mark]:
    """Pytest markers for a language.

    The returned list contains the primary language marker and any
    environment-dependent skip markers shared across the test suite.
    """
    return _LANGUAGE_PYTEST_MARKERS[language]


def _determine_disabled_languages() -> list[Language]:
    """
    Determine which language tests should be disabled (based on the environment)

    :return: the list of disabled languages
    """
    result: list[Language] = []

    java_tests_enabled = True
    if not java_tests_enabled:
        result.append(Language.JAVA)

    clojure_tests_enabled = is_clojure_cli_available()
    if not clojure_tests_enabled:
        result.append(Language.CLOJURE)

    # Disable CPP_CCLS tests if ccls is not available
    ccls_tests_enabled = _sh.which("ccls") is not None
    if not ccls_tests_enabled:
        result.append(Language.CPP_CCLS)

    # Disable CPP (clangd) tests if clangd is not available
    clangd_tests_enabled = _sh.which("clangd") is not None
    if not clangd_tests_enabled:
        result.append(Language.CPP)

    # Disable PHP_PHPACTOR tests if php is not available
    php_tests_enabled = _sh.which("php") is not None
    if not php_tests_enabled:
        result.append(Language.PHP_PHPACTOR)

    al_tests_enabled = True
    if not al_tests_enabled:
        result.append(Language.AL)

    return result


_disabled_languages = _determine_disabled_languages()


def language_tests_enabled(language: Language) -> bool:
    """
    Check if tests for the given language are enabled in the current environment.

    :param language: the language to check
    :return: True if tests for the language are enabled, False otherwise
    """
    return language not in _disabled_languages
