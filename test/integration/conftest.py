"""Stage 1H integration test harness — minimum-scope (v0.1.0).

Boots **rust-analyzer** + **pylsp** + **basedpyright** + **ruff** as
session-scoped fixtures so the smoke integration tests can exercise
the Stage 1A facades against real LSP processes loaded against the
Stage 1H minimum-scope fixture trees (``test/fixtures/calcrs/`` +
``test/fixtures/calcpy/``).

Critical implementation notes
-----------------------------

1. ``LanguageServerConfig.code_language`` (NOT ``language``); see
   ``vendor/serena/src/solidlsp/ls_config.py:596``.
2. ``with srv.start_server():`` is the **sync** context manager
   exposed by ``vendor/serena/src/solidlsp/ls.py:717``; never use
   ``async with``.
3. The three Python LSP adapters (``PylspServer`` /
   ``BasedpyrightServer`` / ``RuffServer``) are *not* registered in
   ``Language.PYTHON.get_ls_class()`` — that mapping points at
   ``PyrightServer``.  The fixtures therefore instantiate each
   adapter class **directly** rather than going through
   ``SolidLanguageServer.create``.
4. Binary discovery uses ``shutil.which``; missing binaries cause
   ``pytest.skip(...)`` so a partial dev environment doesn't fail
   the suite.
5. Cold-start indexing for rust-analyzer takes ~3–5 s on the
   minimum-scope ``calcrs`` fixture; basedpyright pull-mode
   diagnostics need ~1–2 s.  Session scoping amortises the wait
   across all smoke modules.
6. Each LSP is wrapped in a ``contextlib.ExitStack`` so the
   sync ``start_server`` context managers are correctly torn down
   at session end.
7. ``CARGO_BUILD_RUSTC=rustc`` is exported into the rust-analyzer
   environment by the **opt-in** ``test.conftest_dev_host`` pytest
   plugin (auto-loaded via ``pytest_plugins`` in
   ``vendor/serena/test/conftest.py``) when
   ``O2_SCALPEL_LOCAL_HOST=1`` is set. CI does not set the flag and
   inherits a clean environment. See
   ``docs/dev/host-rustc-shim.md`` for the full context.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from solidlsp.ls import SolidLanguageServer


# Note: the developer-host ``CARGO_BUILD_RUSTC=rustc`` shim now lives
# in the opt-in ``test.conftest_dev_host`` pytest plugin (activated by
# ``O2_SCALPEL_LOCAL_HOST=1``). See ``docs/dev/host-rustc-shim.md``.


# ---------------------------------------------------------------------------
# Fixture-tree paths
# ---------------------------------------------------------------------------

INTEGRATION_DIR = Path(__file__).parent.resolve(strict=False)
SERENA_ROOT = INTEGRATION_DIR.parents[1]  # vendor/serena
FIXTURES_ROOT = SERENA_ROOT / "test" / "fixtures"

CALCRS_FIXTURE = FIXTURES_ROOT / "calcrs"
CALCPY_FIXTURE = FIXTURES_ROOT / "calcpy"
CALCPY_DATACLASSES_FIXTURE = FIXTURES_ROOT / "calcpy_dataclasses"
CALCPY_NOTEBOOKS_FIXTURE = FIXTURES_ROOT / "calcpy_notebooks"


@pytest.fixture(scope="session")
def calcrs_workspace() -> Path:
    """Absolute path to the calcrs Cargo workspace fixture root."""
    assert (CALCRS_FIXTURE / "Cargo.toml").exists(), (
        f"calcrs fixture missing Cargo.toml at {CALCRS_FIXTURE}; "
        f"T1-min should have created it."
    )
    return CALCRS_FIXTURE.resolve(strict=False)


@pytest.fixture(scope="session")
def calcpy_workspace() -> Path:
    """Absolute path to the calcpy package fixture root."""
    assert (CALCPY_FIXTURE / "pyproject.toml").exists(), (
        f"calcpy fixture missing pyproject.toml at {CALCPY_FIXTURE}; "
        f"T3-min should have created it."
    )
    return CALCPY_FIXTURE.resolve(strict=False)


@pytest.fixture(scope="session")
def calcpy_dataclasses_workspace() -> Path:
    """Absolute path to the calcpy_dataclasses sub-fixture root.

    Stage 1H Leaf 02 — drives inline-flow integration tests against the
    five-@dataclass shape in ``calcpy_dataclasses/models.py`` plus the
    pre-extracted ``calcpy_dataclasses/sub/extracted.py``. Skip cleanly
    if the fixture pyproject.toml is missing rather than fail collection.
    """
    pyproject = CALCPY_DATACLASSES_FIXTURE / "pyproject.toml"
    if not pyproject.exists():
        pytest.skip(
            f"calcpy_dataclasses fixture missing pyproject.toml at {pyproject}; "
            f"Stage 1H Leaf 02 should have created it."
        )
    return CALCPY_DATACLASSES_FIXTURE.resolve(strict=False)


@pytest.fixture(scope="session")
def calcpy_notebooks_workspace() -> Path:
    """Absolute path to the calcpy_notebooks sub-fixture root.

    Stage 1H Leaf 02 — drives the organize-imports + .ipynb-byte-stability
    integration tests. The fixture intentionally ships an out-of-canonical-
    order import block in ``src/calcpy_min.py`` so ruff's
    ``source.organizeImports.ruff`` and pylsp-rope's ``source.organize_import``
    both have something to reorder.
    """
    pyproject = CALCPY_NOTEBOOKS_FIXTURE / "pyproject.toml"
    if not pyproject.exists():
        pytest.skip(
            f"calcpy_notebooks fixture missing pyproject.toml at {pyproject}; "
            f"Stage 1H Leaf 02 should have created it."
        )
    return CALCPY_NOTEBOOKS_FIXTURE.resolve(strict=False)


# ---------------------------------------------------------------------------
# Binary discovery — skip-if-missing rather than fail
# ---------------------------------------------------------------------------


def _require_binary(name: str) -> str:
    """Return the absolute path to ``name`` or skip the test cleanly."""
    found = shutil.which(name)
    if found is None:
        pytest.skip(f"{name} not on PATH; integration smoke requires it")
    return found


# ---------------------------------------------------------------------------
# Real-LSP fixtures (session-scoped — boot once, reuse across smoke tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def ra_lsp(calcrs_workspace: Path) -> Iterator["SolidLanguageServer"]:
    """Boot rust-analyzer against the calcrs fixture, session-scoped."""
    _require_binary("rust-analyzer")

    # Imported lazily so the module imports cleanly even when the venv
    # is partly broken (collection-time skips remain meaningful).
    from solidlsp.ls import SolidLanguageServer
    from solidlsp.ls_config import Language, LanguageServerConfig

    cfg = LanguageServerConfig(code_language=Language.RUST)
    srv = SolidLanguageServer.create(cfg, str(calcrs_workspace))
    with srv.start_server():
        yield srv


def _build_python_server(adapter_module: str, adapter_class: str, root: Path) -> Any:
    """Instantiate a Stage 1E Python LSP adapter directly.

    The legacy ``Language.PYTHON.get_ls_class()`` registry points at
    ``PyrightServer``; the three Stage 1E adapters
    (``PylspServer``/``BasedpyrightServer``/``RuffServer``) live
    outside that registry and must be constructed manually.
    """
    from importlib import import_module

    from solidlsp.ls_config import Language, LanguageServerConfig
    from solidlsp.settings import SolidLSPSettings

    cls = getattr(import_module(adapter_module), adapter_class)
    cfg = LanguageServerConfig(code_language=Language.PYTHON)
    return cls(cfg, str(root), SolidLSPSettings())


@pytest.fixture(scope="session")
def pylsp_lsp(calcpy_workspace: Path) -> Iterator[Any]:
    """Boot pylsp (with pylsp-rope) against the calcpy fixture."""
    _require_binary("pylsp")
    srv = _build_python_server(
        "solidlsp.language_servers.pylsp_server", "PylspServer", calcpy_workspace
    )
    with srv.start_server():
        yield srv


@pytest.fixture(scope="session")
def basedpyright_lsp(calcpy_workspace: Path) -> Iterator[Any]:
    """Boot basedpyright-langserver against the calcpy fixture."""
    _require_binary("basedpyright-langserver")
    srv = _build_python_server(
        "solidlsp.language_servers.basedpyright_server",
        "BasedpyrightServer",
        calcpy_workspace,
    )
    with srv.start_server():
        yield srv


@pytest.fixture(scope="session")
def ruff_lsp(calcpy_workspace: Path) -> Iterator[Any]:
    """Boot ruff (native LSP) against the calcpy fixture."""
    _require_binary("ruff")
    srv = _build_python_server(
        "solidlsp.language_servers.ruff_server", "RuffServer", calcpy_workspace
    )
    with srv.start_server():
        yield srv


# ---------------------------------------------------------------------------
# Test helper — drive ``request_code_actions`` over a whole-file range
# ---------------------------------------------------------------------------


@pytest.fixture
def whole_file_range(request: pytest.FixtureRequest) -> tuple[dict[str, int], dict[str, int]]:
    """LSP positions covering an entire file.

    Backed by ``solidlsp.util.file_range.compute_file_range`` so callers
    stop duplicating end-of-file coordinate math, and rust-analyzer's
    strict out-of-range rejection (LSP §3.17 — it does not clamp like
    ruff) is satisfied centrally.

    Single usage mode: parametrized via ``indirect`` with a file path:

    .. code-block:: python

        @pytest.mark.parametrize(
            "whole_file_range",
            [str(calcrs / "src" / "lib.rs")],
            indirect=True,
        )
        def test_x(whole_file_range): ...

    Tests that don't want to parametrize must call
    ``solidlsp.util.file_range.compute_file_range`` directly. The
    legacy unparametrized ``(0, 0)..(10_000, 0)`` fallback was removed
    in stage-v0.2.0-review-i3 (TRIZ separation: tests must declare the
    target file rather than rely on a silent generous default).
    """
    target = getattr(request, "param", None)
    if target is None:
        raise pytest.UsageError(
            "whole_file_range requires `indirect=True` with a file path; "
            "the unparametrized fallback was removed in "
            "stage-v0.2.0-review-i3. Either parametrize via "
            "`@pytest.mark.parametrize('whole_file_range', [str(path)], "
            "indirect=True)` or call "
            "`solidlsp.util.file_range.compute_file_range(path)` directly."
        )
    from solidlsp.util.file_range import compute_file_range

    return compute_file_range(target)


# ---------------------------------------------------------------------------
# Stage 1H T8/T9 — WorkspaceEdit round-trip helper (Rust assist suites)
# ---------------------------------------------------------------------------


@pytest.fixture
def assert_workspace_edit_round_trip():
    """Apply a WorkspaceEdit to the workspace files and assert >=1 TextEdit landed.

    Uses the v0.3.0 pure-python applier landed at
    ``serena.tools.scalpel_facades._apply_workspace_edit_to_disk`` (see project
    memory ``project_v0_3_0_facade_application.md``). The applier returns the
    count of TextEdits actually applied; 0 means "no-op" (non-file URI or
    missing target on disk) and is treated as a hard failure here so tests
    surface broken edits rather than silently passing.

    The helper deliberately stops at "edits hit disk". Per-suite callers may
    layer additional assertions (cargo check, post-diagnostics delta) on top
    of the returned count when they care about post-apply semantics.
    """
    from serena.tools.scalpel_facades import _apply_workspace_edit_to_disk

    def _check(edit: dict) -> int:
        applied_count = _apply_workspace_edit_to_disk(edit)
        assert applied_count > 0, (
            "WorkspaceEdit applied 0 TextEdits — likely non-file URI or "
            "missing target on disk."
        )
        return applied_count

    return _check


# ---------------------------------------------------------------------------
# Stage 1H T10 — 3-server Python MultiServerCoordinator
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def python_coordinator(
    pylsp_lsp: Any,
    basedpyright_lsp: Any,
    ruff_lsp: Any,
) -> Any:
    """3-server Python ``MultiServerCoordinator`` for merge-priority assertions.

    Wraps the three session-scoped sync ``SolidLanguageServer`` adapters in
    ``_AsyncAdapter`` (per v0.2.0 follow-up #03 contract — see
    ``serena.refactoring._async_check.assert_servers_async_callable``) and
    constructs a ``MultiServerCoordinator`` keyed by the three canonical
    Python provenance ids: ``pylsp-rope`` / ``basedpyright`` / ``ruff``.

    Skip cleanly with a clear message if construction fails so suites that
    depend on this fixture (organize-imports merge-priority, etc.) don't
    wedge collection on partial dev hosts.
    """
    try:
        from serena.refactoring.multi_server import MultiServerCoordinator
        from serena.tools.scalpel_runtime import _AsyncAdapter
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"python_coordinator unavailable (import error): {exc!r}")

    try:
        servers: dict[str, Any] = {
            "pylsp-rope": _AsyncAdapter(pylsp_lsp),
            "basedpyright": _AsyncAdapter(basedpyright_lsp),
            "ruff": _AsyncAdapter(ruff_lsp),
        }
        return MultiServerCoordinator(servers)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"python_coordinator unavailable (construct error): {exc!r}")


# ---------------------------------------------------------------------------
# Provenance — record what Python the harness ran under (debug aid).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def harness_provenance() -> Iterator[None]:
    """Print one line of provenance once per session for triage."""
    sys.stderr.write(
        "\n[stage-1h harness] python="
        f"{sys.version.split()[0]} "
        f"calcrs={CALCRS_FIXTURE} "
        f"calcpy={CALCPY_FIXTURE}\n"
    )
    yield
