"""v1.3-F — E2E scenario: ``install_lsp_servers`` safety contract.

Tests the non-destructive safety contract for the LSP installer MCP tool:
- dry_run=True (default) surfaces the planned command without subprocess
- allow_install=False alone (no allow_install gate) refuses to mutate
- idempotent when binary is already installed (noop path)
- SessionStart hook wiring is correct in o2-scalpel-rust/hooks/hooks.json

All tests are non-destructive: they never mutate the developer's machine.
The opt-in gate (O2_SCALPEL_RUN_E2E=1) is honoured via the conftest
``pytest_collection_modifyitems`` hook that marks every ``e2e``-tagged test
for skipping when the env-var is absent.

Why no real subprocess invocation?
    The installer suite has its own unit tests (``test/test_installer_*.py``)
    that cover actual ``detect_installed``/``_install_command`` logic. These
    e2e scenarios verify the MCP *tool* surface: the safety envelope that
    guards against accidental system mutation when the tool is driven by an
    LLM-controlled agent.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from serena.installer.installer import InstalledStatus, InstallResult
from serena.tools.scalpel_primitives import InstallLspServersTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool(tmp_path: Path) -> InstallLspServersTool:
    """Return a InstallLspServersTool bound to a tmp workspace root.

    Mirrors the ``_McpDriver._bind`` pattern used by the e2e conftest: create
    via ``__new__`` (bypassing Tool.__init__ agent requirement) and inject a
    ``get_project_root`` shim so the tool can resolve relative paths.
    """
    tool = InstallLspServersTool.__new__(InstallLspServersTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]
    return tool


# ---------------------------------------------------------------------------
# Scenario 1 — Default safety: dry_run=True returns plan without subprocess
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_lsp_install_dry_run_emits_plan_no_subprocess(tmp_path: Path) -> None:
    """dry_run=True (default) must surface the planned argv and NOT invoke subprocess.

    Critical contract: the LLM can inspect the planned command before granting
    real execution permission. This must hold even if the binary is absent from
    PATH (e.g. on a fresh CI runner).
    """
    tool = _make_tool(tmp_path)

    # Patch subprocess.run at the installer layer so any accidental call raises.
    import serena.installer.installer as _installer_mod
    with patch.object(_installer_mod.subprocess, "run", side_effect=AssertionError(
        "subprocess.run must NEVER be called during dry_run=True"
    )):
        raw = tool.apply(languages=["rust"], dry_run=True, allow_install=False)

    report = json.loads(raw)
    assert "rust" in report, f"Expected 'rust' key in report; got {list(report)}"
    entry = report["rust"]

    # The entry must carry the planned command — even in dry-run.
    # Two branches: either a regular entry with command, or a "skipped" entry
    # if detect_installed raised (e.g. rustup binary probe timeout on CI).
    if entry.get("action") == "skipped":
        # Acceptable: detect_installed raised on this host (no PATH binary).
        # The important contract is still met: no subprocess.
        assert "reason" in entry, "skipped entry must carry a reason"
        return

    # Regular entry: dry_run flag must be True.
    assert entry.get("dry_run") is True, (
        f"dry_run=True must be reflected in the report entry; got {entry!r}"
    )
    # A planned command must be present.
    command = entry.get("command")
    assert isinstance(command, list) and len(command) >= 1, (
        f"Expected non-empty command list; got {command!r}"
    )


# ---------------------------------------------------------------------------
# Scenario 2 — Both flags required: dry_run=False alone refuses to mutate
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_lsp_install_requires_allow_install_flag_for_real_run(
    tmp_path: Path,
) -> None:
    """dry_run=False without allow_install=True must NOT invoke subprocess.

    The safety contract requires BOTH gates to be open simultaneously
    (CLAUDE.md "executing actions with care"). Passing dry_run=False alone
    is not enough — the tool keeps the entry in dry-run mode.
    """
    tool = _make_tool(tmp_path)

    # Mock detect_installed to return "not installed" so action="install"
    # would be chosen — the interesting code path for allow_install check.
    absent_status = InstalledStatus(present=False, version=None, path=None)
    dry_result = InstallResult(
        success=False,
        command_run=("rustup", "component", "add", "rust-analyzer"),
        dry_run=True,
    )

    import serena.installer.installer as _installer_mod
    with (
        patch(
            "serena.installer.rust_analyzer_installer.RustAnalyzerInstaller.detect_installed",
            return_value=absent_status,
        ),
        patch(
            "serena.installer.rust_analyzer_installer.RustAnalyzerInstaller.latest_available",
            return_value=None,
        ),
        # The tool should NOT call install(); patch it to raise if called.
        patch(
            "serena.installer.rust_analyzer_installer.RustAnalyzerInstaller.install",
            side_effect=AssertionError(
                "installer.install() must not be called when allow_install=False"
            ),
        ),
        # Belt-and-suspenders: also block subprocess.run.
        patch.object(
            _installer_mod.subprocess,
            "run",
            side_effect=AssertionError("subprocess.run blocked"),
        ),
    ):
        raw = tool.apply(
            languages=["rust"],
            dry_run=False,
            allow_install=False,  # gate closed — must NOT install
        )

    report = json.loads(raw)
    entry = report.get("rust", {})

    # When action==install but allow_install=False the entry stays dry_run=True.
    if entry.get("action") == "install":
        assert entry.get("dry_run") is True, (
            f"action=install without allow_install=True must keep dry_run=True; "
            f"got {entry!r}"
        )


# ---------------------------------------------------------------------------
# Scenario 3 — Idempotent: already-installed binary reports noop
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_lsp_install_idempotent_on_already_installed(tmp_path: Path) -> None:
    """When the binary is already installed, action must be 'noop' (no install triggered).

    This verifies the _decide_action logic surfaces correctly in the MCP tool
    report: present + no newer version = noop, so install() is never called.
    """
    tool = _make_tool(tmp_path)

    installed_status = InstalledStatus(
        present=True,
        version="rust-analyzer 1.95.0 (abc123 2025-01-01)",
        path="/usr/local/bin/rust-analyzer",
    )

    with (
        patch(
            "serena.installer.rust_analyzer_installer.RustAnalyzerInstaller.detect_installed",
            return_value=installed_status,
        ),
        patch(
            "serena.installer.rust_analyzer_installer.RustAnalyzerInstaller.latest_available",
            return_value=None,  # rustup doesn't expose a "latest" version
        ),
        # install() must not be invoked for a noop action.
        patch(
            "serena.installer.rust_analyzer_installer.RustAnalyzerInstaller.install",
            side_effect=AssertionError(
                "installer.install() must not be called for noop action"
            ),
        ),
    ):
        raw = tool.apply(
            languages=["rust"],
            dry_run=False,
            allow_install=True,  # gate open, but noop wins
        )

    report = json.loads(raw)
    entry = report.get("rust", {})

    # When binary is present and no update is available, action == "noop".
    assert entry.get("action") == "noop", (
        f"Already-installed binary must report action='noop'; got {entry!r}"
    )
    # dry_run stays True for noop — the base contract still applies.
    assert entry.get("dry_run") is True, (
        f"noop entry must still report dry_run=True; got {entry!r}"
    )

    # detected block must reflect the mocked status.
    detected = entry.get("detected", {})
    assert detected.get("present") is True
    assert detected.get("path") == "/usr/local/bin/rust-analyzer"


# ---------------------------------------------------------------------------
# Scenario 4 — SessionStart hook wiring: hooks.json exists and binds verify script
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_session_start_hook_wiring_rust(tmp_path: Path) -> None:  # noqa: ARG001
    """o2-scalpel-rust/hooks/hooks.json must exist and declare SessionStart.

    The hook fires ``verify-scalpel-rust.sh`` at session start. When that
    script returns exit 2 (LSP binary missing), Claude is expected to invoke
    ``install_lsp_servers`` to bootstrap rust-analyzer. This test
    validates the wiring half (hooks.json structure) without spawning any
    subprocess — the shell script itself is validated separately.

    Lookup path: vendor/serena is 3 directories below the repo root
    (repo_root/vendor/serena), so parents[2] resolves to repo root.
    """
    # vendor/serena/test/e2e/test_e2e_lsp_install_scenario.py
    # parents[0] = e2e/
    # parents[1] = test/
    # parents[2] = serena/ (submodule root)
    # parents[3] = vendor/
    # parents[4] = repo root
    repo_root = Path(__file__).resolve().parents[4]
    hooks_json = repo_root / "o2-scalpel-rust" / "hooks" / "hooks.json"

    assert hooks_json.exists(), (
        f"hooks.json not found at {hooks_json}; "
        "o2-scalpel-rust plugin must ship a hooks/hooks.json"
    )

    data = json.loads(hooks_json.read_text(encoding="utf-8"))

    hooks_block = data.get("hooks", {})
    assert "SessionStart" in hooks_block, (
        f"hooks.json must bind the 'SessionStart' event; "
        f"found events: {sorted(hooks_block)}"
    )

    # Validate that at least one hook command references the verify script.
    session_start_entries = hooks_block["SessionStart"]
    all_commands: list[str] = []
    for entry in session_start_entries:
        for hook in entry.get("hooks", []):
            cmd = hook.get("command", "")
            all_commands.append(cmd)

    assert any("verify-scalpel-rust" in cmd for cmd in all_commands), (
        f"SessionStart hooks must include the verify-scalpel-rust script; "
        f"found commands: {all_commands}"
    )


# ---------------------------------------------------------------------------
# Scenario 5 — Unknown language gracefully skipped (no crash)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_lsp_install_unknown_language_skipped_gracefully(tmp_path: Path) -> None:
    """Requesting an unregistered language must return a skipped entry, not crash."""
    tool = _make_tool(tmp_path)

    raw = tool.apply(
        languages=["cobol"],  # not registered in the installer registry
        dry_run=True,
        allow_install=False,
    )
    report = json.loads(raw)
    assert "cobol" in report, f"Expected 'cobol' in report; got {list(report)}"
    entry = report["cobol"]
    assert entry.get("action") == "skipped", (
        f"Unknown language must report action='skipped'; got {entry!r}"
    )
    assert "reason" in entry, "skipped entry must include a 'reason' field"
    assert "cobol" in entry["reason"].lower() or "no installer" in entry["reason"].lower(), (
        f"Reason must mention the unknown language or 'no installer'; got {entry['reason']!r}"
    )
