"""Stage 1I - uvx --from <local-path> smoke for the generated plugin trees.

Boots the MCP server via ``uvx`` against each generated ``.mcp.json``,
sends a JSON-RPC ``tools/list`` request on stdin, and asserts that
the response contains at least the always-on scalpel tools.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SMOKE_SCRIPT = REPO_ROOT / "scripts" / "stage_1i_uvx_smoke.sh"

# Always-on scalpel tools per scope-report section 5.1 (subset that is
# language-agnostic and ships at MVP regardless of strategy).
EXPECTED_TOOLS_MIN: set[str] = {
    "scalpel_split_file",
    "scalpel_extract",
    "scalpel_inline",
    "scalpel_rename",
    "scalpel_imports_organize",
    "scalpel_capabilities_list",
    "scalpel_apply_capability",
    "scalpel_dry_run_compose",
}


@pytest.fixture(scope="module")
def uvx_available() -> None:
    if shutil.which("uvx") is None:
        pytest.skip("uvx not installed on this host; install via 'pip install uv'")


@pytest.fixture(scope="module")
def smoke_script_exists() -> None:
    if not SMOKE_SCRIPT.exists():
        pytest.skip(f"{SMOKE_SCRIPT} missing - re-run T6 step 2")
    if not os.access(SMOKE_SCRIPT, os.X_OK):
        pytest.skip(f"{SMOKE_SCRIPT} not executable - chmod +x and retry")


@pytest.fixture(scope="module")
def serena_mcp_entry_available() -> None:
    """Skip if the Serena fork does not yet expose a ``serena-mcp`` script entry.

    Stage 1J committed ``.mcp.json`` files referencing ``serena-mcp``; the
    Serena fork is expected to add a ``[project.scripts] serena-mcp = ...``
    entry pointing at a callable in ``serena.cli``. Until that lands,
    ``uvx ... serena-mcp`` cannot resolve and the smoke is moot.
    """
    pyproject = REPO_ROOT / "vendor" / "serena" / "pyproject.toml"
    if not pyproject.exists():
        pytest.skip("vendor/serena/pyproject.toml missing")
    text = pyproject.read_text(encoding="utf-8")
    if "serena-mcp" not in text:
        pytest.skip(
            "Serena fork has no 'serena-mcp' [project.scripts] entry; "
            "Stage 1J / Serena follow-up. T6 smoke deferred."
        )


@pytest.mark.parametrize("language", ["rust", "python"])
def test_uvx_smoke_launches_and_lists_tools(
    uvx_available: None,
    smoke_script_exists: None,
    serena_mcp_entry_available: None,
    language: str,
) -> None:
    """Run the smoke driver for one language and assert tools/list returns
    the expected always-on scalpel tool names."""
    proc = subprocess.run(
        [str(SMOKE_SCRIPT), language],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, (
        f"smoke failed for {language}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    tools: set[str] = set(proc.stdout.strip().splitlines())
    missing = EXPECTED_TOOLS_MIN - tools
    assert not missing, f"missing tools for {language}: {missing}; got: {tools}"
