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

from serena.refactoring import STRATEGY_REGISTRY as _STRATEGY_REGISTRY_WARMUP  # noqa: F401  (registry warm-up)
del _STRATEGY_REGISTRY_WARMUP  # silence Pyright while preserving import side-effect
from serena.tools.scalpel_facades import (
    # Stage 2A MVP facades
    ScalpelExtractTool,
    ScalpelImportsOrganizeTool,
    ScalpelInlineTool,
    ScalpelRenameTool,
    ScalpelSplitFileTool,
    ScalpelTransactionCommitTool,
    # Stage 3 Rust facades (waves A-C)
    ScalpelChangeReturnTypeTool,
    ScalpelChangeTypeShapeTool,
    ScalpelChangeVisibilityTool,
    ScalpelCompleteMatchArmsTool,
    ScalpelConvertModuleLayoutTool,
    ScalpelExpandGlobImportsTool,
    ScalpelExpandMacroTool,
    ScalpelExtractLifetimeTool,
    ScalpelGenerateMemberTool,
    ScalpelGenerateTraitImplScaffoldTool,
    ScalpelTidyStructureTool,
    ScalpelVerifyAfterRefactorTool,
    # Stage 3 Python facades (waves A-B)
    ScalpelAutoImportSpecializedTool,
    ScalpelConvertToMethodObjectTool,
    ScalpelFixLintsTool,
    ScalpelGenerateFromUndefinedTool,
    ScalpelIgnoreDiagnosticTool,
    ScalpelIntroduceParameterTool,
    ScalpelLocalToFieldTool,
    ScalpelUseFunctionTool,
    # v1.1.1 Markdown facades
    ScalpelExtractSectionTool,
    ScalpelOrganizeLinksTool,
    ScalpelRenameHeadingTool,
    ScalpelSplitDocTool,
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

# v1.2.2 playground per spec docs/superpowers/specs/2026-04-28-rust-plugin-e2e-playground-spec.md § 4.3.
# parents[4] resolves vendor/serena/test/e2e/conftest.py up four directory levels:
#   parents[0]=e2e/, parents[1]=test/, parents[2]=serena/, parents[3]=vendor/, parents[4]=repo root.
PLAYGROUND_RUST_BASELINE = Path(__file__).resolve().parents[4] / "playground" / "rust"

# v1.3-C Python playground — mirrors PLAYGROUND_RUST_BASELINE structure.
PLAYGROUND_PYTHON_BASELINE = Path(__file__).resolve().parents[4] / "playground" / "python"

# v1.3-D Markdown playground — mirrors PLAYGROUND_RUST_BASELINE + PLAYGROUND_PYTHON_BASELINE.
PLAYGROUND_MARKDOWN_BASELINE = Path(__file__).resolve().parents[4] / "playground" / "markdown"


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


@pytest.fixture(scope="session")
def marksman_bin() -> str:
    return _which_or_skip("marksman")


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
def playground_rust_root(tmp_path: Path) -> Path:
    """Per-test clone of the playground/rust baseline; target/ stripped post-copy."""
    dest = tmp_path / "playground_rust"
    shutil.copytree(PLAYGROUND_RUST_BASELINE, dest, dirs_exist_ok=False)
    target = dest / "target"
    if target.exists():
        shutil.rmtree(target)
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
        tool = tool_cls.__new__(tool_cls)  # pyright: ignore[reportCallIssue]
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

    # --- Stage 3 Rust facades (waves A-C) ---

    def convert_module_layout(self, **kwargs: Any) -> str:
        return self._bind(ScalpelConvertModuleLayoutTool).apply(**kwargs)

    def change_visibility(self, **kwargs: Any) -> str:
        return self._bind(ScalpelChangeVisibilityTool).apply(**kwargs)

    def tidy_structure(self, **kwargs: Any) -> str:
        return self._bind(ScalpelTidyStructureTool).apply(**kwargs)

    def change_type_shape(self, **kwargs: Any) -> str:
        return self._bind(ScalpelChangeTypeShapeTool).apply(**kwargs)

    def change_return_type(self, **kwargs: Any) -> str:
        return self._bind(ScalpelChangeReturnTypeTool).apply(**kwargs)

    def complete_match_arms(self, **kwargs: Any) -> str:
        return self._bind(ScalpelCompleteMatchArmsTool).apply(**kwargs)

    def extract_lifetime(self, **kwargs: Any) -> str:
        return self._bind(ScalpelExtractLifetimeTool).apply(**kwargs)

    def expand_glob_imports(self, **kwargs: Any) -> str:
        return self._bind(ScalpelExpandGlobImportsTool).apply(**kwargs)

    def generate_trait_impl_scaffold(self, **kwargs: Any) -> str:
        return self._bind(ScalpelGenerateTraitImplScaffoldTool).apply(**kwargs)

    def generate_member(self, **kwargs: Any) -> str:
        return self._bind(ScalpelGenerateMemberTool).apply(**kwargs)

    def expand_macro(self, **kwargs: Any) -> str:
        return self._bind(ScalpelExpandMacroTool).apply(**kwargs)

    def verify_after_refactor(self, **kwargs: Any) -> str:
        return self._bind(ScalpelVerifyAfterRefactorTool).apply(**kwargs)

    # --- Stage 3 Python facades (waves A-B) ---

    def convert_to_method_object(self, **kwargs: Any) -> str:
        return self._bind(ScalpelConvertToMethodObjectTool).apply(**kwargs)

    def local_to_field(self, **kwargs: Any) -> str:
        return self._bind(ScalpelLocalToFieldTool).apply(**kwargs)

    def use_function(self, **kwargs: Any) -> str:
        return self._bind(ScalpelUseFunctionTool).apply(**kwargs)

    def introduce_parameter(self, **kwargs: Any) -> str:
        return self._bind(ScalpelIntroduceParameterTool).apply(**kwargs)

    def generate_from_undefined(self, **kwargs: Any) -> str:
        return self._bind(ScalpelGenerateFromUndefinedTool).apply(**kwargs)

    def auto_import_specialized(self, **kwargs: Any) -> str:
        return self._bind(ScalpelAutoImportSpecializedTool).apply(**kwargs)

    def fix_lints(self, **kwargs: Any) -> str:
        return self._bind(ScalpelFixLintsTool).apply(**kwargs)

    def ignore_diagnostic(self, **kwargs: Any) -> str:
        return self._bind(ScalpelIgnoreDiagnosticTool).apply(**kwargs)

    # --- v1.1.1 Markdown facades ---

    def rename_heading(self, **kwargs: Any) -> str:
        return self._bind(ScalpelRenameHeadingTool).apply(**kwargs)

    def split_doc(self, **kwargs: Any) -> str:
        return self._bind(ScalpelSplitDocTool).apply(**kwargs)

    def extract_section(self, **kwargs: Any) -> str:
        return self._bind(ScalpelExtractSectionTool).apply(**kwargs)

    def organize_links(self, **kwargs: Any) -> str:
        return self._bind(ScalpelOrganizeLinksTool).apply(**kwargs)


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


@pytest.fixture
def mcp_driver_playground_rust(
    scalpel_runtime: ScalpelRuntime, playground_rust_root: Path
) -> _McpDriver:
    """v1.2.2 playground driver: mirrors mcp_driver_rust but binds to playground_rust_root."""
    del scalpel_runtime  # used only for setup/teardown ordering
    return _McpDriver(project_root=playground_rust_root)


@pytest.fixture
def playground_python_root(tmp_path: Path) -> Path:
    """v1.3-C Python playground clone under tmp_path.

    Mirrors ``playground_rust_root``: clones the baseline workspace into an
    isolated ``tmp_path`` directory and strips ``__pycache__/``, ``.venv/``,
    and ``.pytest_cache/`` to prevent stale bytecode from influencing
    pylsp / basedpyright analysis.
    """
    dest = tmp_path / "playground_python"
    shutil.copytree(PLAYGROUND_PYTHON_BASELINE, dest, dirs_exist_ok=False)
    # Strip transient directories that confuse LSP indexing.
    for purge in ["__pycache__", ".venv", ".pytest_cache"]:
        for hit in dest.rglob(purge):
            if hit.is_dir():
                shutil.rmtree(hit, ignore_errors=True)
    return dest.resolve(strict=False)


@pytest.fixture
def mcp_driver_playground_python(
    scalpel_runtime: ScalpelRuntime, playground_python_root: Path
) -> _McpDriver:
    """v1.3-C playground driver: mirrors mcp_driver_python but binds to playground_python_root."""
    del scalpel_runtime  # used only for setup/teardown ordering
    return _McpDriver(project_root=playground_python_root)


@pytest.fixture
def playground_markdown_root(tmp_path: Path) -> Path:
    """v1.3-D Markdown playground clone under tmp_path.

    Mirrors ``playground_python_root``: clones the baseline workspace into an
    isolated ``tmp_path`` directory. No transient directories to strip for
    plain-text Markdown (no bytecode or build caches).
    """
    dest = tmp_path / "playground_markdown"
    shutil.copytree(PLAYGROUND_MARKDOWN_BASELINE, dest, dirs_exist_ok=False)
    return dest.resolve(strict=False)


@pytest.fixture
def mcp_driver_playground_markdown(
    scalpel_runtime: ScalpelRuntime, playground_markdown_root: Path
) -> _McpDriver:
    """v1.3-D playground driver: mirrors mcp_driver_playground_python but binds to playground_markdown_root."""
    del scalpel_runtime  # used only for setup/teardown ordering
    return _McpDriver(project_root=playground_markdown_root)


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
