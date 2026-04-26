"""Stage 2B end-to-end harness.

Boots the full ScalpelRuntime against four real LSP processes (rust-analyzer,
pylsp, basedpyright, ruff) and exposes a sync MCP-driver fixture that lets
each scenario test invoke the 6 Stage 2A facades + 5 Stage 1G primitives
the same way an MCP client would.

Opt-in: set ``O2_SCALPEL_RUN_E2E=1`` or run with ``pytest -m e2e``.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from serena.refactoring import STRATEGY_REGISTRY  # noqa: F401  (registry warm-up)
from serena.tools.scalpel_facades import (
    ScalpelExtractTool,
    ScalpelImportsOrganizeTool,
    ScalpelInlineTool,
    ScalpelRenameTool,
    ScalpelSplitFileTool,
    ScalpelTransactionCommitTool,
)
from serena.tools.scalpel_primitives import (
    ScalpelCapabilitiesListTool,
    ScalpelDryRunComposeTool,
    ScalpelRollbackTool,
    ScalpelTransactionRollbackTool,
    ScalpelWorkspaceHealthTool,
)
from serena.tools.scalpel_runtime import ScalpelRuntime

E2E_DIR = Path(__file__).parent
FIXTURES_DIR = E2E_DIR / "fixtures"
CALCRS_BASELINE = FIXTURES_DIR / "calcrs_e2e"
CALCPY_BASELINE = FIXTURES_DIR / "calcpy_e2e"


def _e2e_enabled() -> bool:
    """Return True iff the e2e suite is opted-in for this pytest session."""
    if os.environ.get("O2_SCALPEL_RUN_E2E") == "1":
        return True
    return any("e2e" in arg for arg in sys.argv)


def pytest_collection_modifyitems(config, items):  # noqa: ARG001 - pytest hook
    """Skip every e2e-marked test unless the gate env var is set."""
    del config
    if _e2e_enabled():
        return
    skip_marker = pytest.mark.skip(
        reason="e2e suite gated; set O2_SCALPEL_RUN_E2E=1 or pytest -m e2e"
    )
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip_marker)


def _which_or_skip(binary: str) -> str:
    """Return the absolute path to ``binary`` on PATH; pytest.skip if missing."""
    path = shutil.which(binary)
    if path is None:
        pytest.skip(f"{binary} not on PATH; required for Stage 2B E2E")
    return path


@pytest.fixture(scope="session")
def cargo_bin() -> str:
    return _which_or_skip("cargo")


@pytest.fixture(scope="session")
def python_bin() -> str:
    return _which_or_skip("python3")


@pytest.fixture(scope="session")
def rust_analyzer_bin() -> str:
    return _which_or_skip("rust-analyzer")


@pytest.fixture(scope="session")
def pylsp_bin() -> str:
    return _which_or_skip("pylsp")


@pytest.fixture(scope="session")
def basedpyright_bin() -> str:
    return _which_or_skip("basedpyright-langserver")


@pytest.fixture(scope="session")
def ruff_bin() -> str:
    return _which_or_skip("ruff")


@pytest.fixture
def calcrs_e2e_root(tmp_path: Path) -> Path:
    """Per-test clone of the calcrs_e2e baseline (so cargo sees a clean tree)."""
    dest = tmp_path / "calcrs_e2e"
    shutil.copytree(CALCRS_BASELINE, dest, dirs_exist_ok=False)
    target_dir = dest / "target"
    if target_dir.exists():
        shutil.rmtree(target_dir)
    return dest.resolve(strict=False)


@pytest.fixture
def calcpy_e2e_root(tmp_path: Path) -> Path:
    """Per-test clone of the calcpy_e2e baseline."""
    dest = tmp_path / "calcpy_e2e"
    shutil.copytree(CALCPY_BASELINE, dest, dirs_exist_ok=False)
    return dest.resolve(strict=False)


@pytest.fixture
def scalpel_runtime() -> Iterator[ScalpelRuntime]:
    """Boot a fresh ScalpelRuntime singleton for one test.

    The runtime's spawn factory (Stage 2A T1) discovers the four LSP binaries
    via ``shutil.which`` and lazily spawns them on first ``LspPool.acquire``.
    """
    ScalpelRuntime.reset_for_testing()
    runtime = ScalpelRuntime.instance()
    yield runtime
    ScalpelRuntime.reset_for_testing()


class _McpDriver:
    """Thin sync wrapper that mirrors the MCP-server tool surface.

    Each method instantiates the relevant Tool subclass (bypassing the
    Tool.__init__ agent requirement via ``__new__``) and calls ``apply``
    with the same kwargs an MCP client would pass. Tool subclasses bind to
    the singleton ScalpelRuntime via ``ScalpelRuntime.instance()``, so the
    ``scalpel_runtime`` fixture's reset-for-test isolates state.
    """

    def __init__(self, project_root: Path) -> None:
        self._root = project_root

    def _bind(self, tool_cls: type) -> Any:
        tool = tool_cls.__new__(tool_cls)
        tool.get_project_root = lambda: str(self._root)  # type: ignore[method-assign]
        return tool

    def split_file(self, **kwargs: Any) -> str:
        return self._bind(ScalpelSplitFileTool).apply(**kwargs)

    def extract(self, **kwargs: Any) -> str:
        return self._bind(ScalpelExtractTool).apply(**kwargs)

    def inline(self, **kwargs: Any) -> str:
        return self._bind(ScalpelInlineTool).apply(**kwargs)

    def rename(self, **kwargs: Any) -> str:
        return self._bind(ScalpelRenameTool).apply(**kwargs)

    def imports_organize(self, **kwargs: Any) -> str:
        return self._bind(ScalpelImportsOrganizeTool).apply(**kwargs)

    def transaction_commit(self, transaction_id: str) -> str:
        return self._bind(ScalpelTransactionCommitTool).apply(
            transaction_id=transaction_id
        )

    def dry_run_compose(self, steps: list[dict[str, Any]]) -> str:
        return self._bind(ScalpelDryRunComposeTool).apply(steps=steps)

    def rollback(self, checkpoint_id: str) -> str:
        return self._bind(ScalpelRollbackTool).apply(checkpoint_id=checkpoint_id)

    def transaction_rollback(self, transaction_id: str) -> str:
        return self._bind(ScalpelTransactionRollbackTool).apply(
            transaction_id=transaction_id
        )

    def workspace_health(self) -> str:
        return self._bind(ScalpelWorkspaceHealthTool).apply()

    def capabilities_list(self, language: str) -> str:
        return self._bind(ScalpelCapabilitiesListTool).apply(language=language)


@pytest.fixture
def mcp_driver_rust(
    scalpel_runtime: ScalpelRuntime, calcrs_e2e_root: Path
) -> _McpDriver:
    del scalpel_runtime  # used only for setup/teardown ordering
    return _McpDriver(project_root=calcrs_e2e_root)


@pytest.fixture
def mcp_driver_python(
    scalpel_runtime: ScalpelRuntime, calcpy_e2e_root: Path
) -> _McpDriver:
    del scalpel_runtime
    return _McpDriver(project_root=calcpy_e2e_root)


# --- wall-clock budget recorder (consumed by T13) -------------------------


_WALL_CLOCK_BUCKET: list[tuple[str, float]] = []


def get_wall_clock_bucket() -> list[tuple[str, float]]:
    """T13 reads this at session-end."""
    return _WALL_CLOCK_BUCKET


@pytest.fixture
def wall_clock_record(request) -> Iterator[None]:
    """Append per-test elapsed seconds to a module-level list.

    T13 (`test_wall_clock_budget.py`) reads the list at session-end and
    asserts the aggregate <= 12 min on CI.
    """
    t0 = time.monotonic()
    yield
    elapsed = time.monotonic() - t0
    _WALL_CLOCK_BUCKET.append((request.node.name, elapsed))
