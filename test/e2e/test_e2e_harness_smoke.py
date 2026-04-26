"""T1 smoke test — assert the Stage 2B harness wires up cleanly.

Does not run any facade; just proves:
  - the e2e marker is registered;
  - the scalpel_runtime fixture yields a ScalpelRuntime;
  - both fixture trees are copied to per-test tmp dirs;
  - the _McpDriver exposes every facade + primitive.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.mark.e2e
def test_runtime_boots(scalpel_runtime: ScalpelRuntime) -> None:
    assert isinstance(scalpel_runtime, ScalpelRuntime)
    assert ScalpelRuntime.instance() is scalpel_runtime


@pytest.mark.e2e
def test_calcrs_root_clones(calcrs_e2e_root: Path) -> None:
    assert (calcrs_e2e_root / "Cargo.toml").exists()
    assert (calcrs_e2e_root / "src" / "lib.rs").exists()
    assert (calcrs_e2e_root / "tests" / "byte_identity_test.rs").exists()


@pytest.mark.e2e
def test_calcpy_root_clones(calcpy_e2e_root: Path) -> None:
    assert (calcpy_e2e_root / "pyproject.toml").exists()
    assert (calcpy_e2e_root / "calcpy" / "calcpy.py").exists()
    assert (calcpy_e2e_root / "calcpy" / "__init__.py").exists()


@pytest.mark.e2e
def test_mcp_drivers_bind(mcp_driver_rust, mcp_driver_python) -> None:
    for driver in (mcp_driver_rust, mcp_driver_python):
        for method_name in (
            "split_file", "extract", "inline", "rename",
            "imports_organize", "transaction_commit",
            "dry_run_compose", "rollback", "transaction_rollback",
            "workspace_health", "capabilities_list",
        ):
            assert callable(getattr(driver, method_name))
