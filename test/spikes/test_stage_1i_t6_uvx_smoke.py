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


@pytest.mark.usefixtures("uvx_available", "smoke_script_exists")
@pytest.mark.parametrize("language", ["rust", "python"])
def test_uvx_smoke_launches_and_lists_tools(
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
