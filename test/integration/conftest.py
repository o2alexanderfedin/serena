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
   environment to defeat the user's global ``rust-fv-driver`` cargo
   wrapper (an environmental quirk; see
   ``test/spikes/test_spike_s3_apply_edit_reverse.py:24`` for the
   same workaround).
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from solidlsp.ls import SolidLanguageServer


# Neutralise the user's global ``rust-fv-driver`` cargo config wrapper
# before any rust-analyzer subprocess inherits the environment.
os.environ.setdefault("CARGO_BUILD_RUSTC", "rustc")


# ---------------------------------------------------------------------------
# Fixture-tree paths
# ---------------------------------------------------------------------------

INTEGRATION_DIR = Path(__file__).parent.resolve(strict=False)
SERENA_ROOT = INTEGRATION_DIR.parents[1]  # vendor/serena
FIXTURES_ROOT = SERENA_ROOT / "test" / "fixtures"

CALCRS_FIXTURE = FIXTURES_ROOT / "calcrs"
CALCPY_FIXTURE = FIXTURES_ROOT / "calcpy"


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
def whole_file_range() -> tuple[dict[str, int], dict[str, int]]:
    """LSP positions covering the start of a file to a generously large end.

    Real code-action providers clamp to the actual document length, so
    ``end.line=10_000`` is safe and removes the need for tests to know
    the precise file length up front.
    """
    return ({"line": 0, "character": 0}, {"line": 10_000, "character": 0})


# ---------------------------------------------------------------------------
# Provenance — record what Python the harness ran under (debug aid).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _harness_provenance() -> Iterator[None]:
    """Print one line of provenance once per session for triage."""
    sys.stderr.write(
        "\n[stage-1h harness] python="
        f"{sys.version.split()[0]} "
        f"calcrs={CALCRS_FIXTURE} "
        f"calcpy={CALCPY_FIXTURE}\n"
    )
    yield
