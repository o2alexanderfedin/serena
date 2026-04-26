"""Stage 1J T12 — End-to-end SessionStart hook coverage.

Generates the rust plugin tree via the parent-repo Makefile then runs
the emitted ``hooks/verify-scalpel-rust.sh`` under controlled $PATH
manipulation to assert both pass and fail paths behave as documented.

The full uvx install + ``tools/list`` MCP round-trip is deferred (the
``serena-mcp`` entry point ships under the ``serena`` click root, not
as a standalone binary, and standing up a real LSP server in CI breaks
the watchdog budget). The hook coverage here proves the install-time
gate works which is the intent of T12.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("make") is None, reason="make not installed"
)

REPO = Path(__file__).resolve().parents[4]


def _generate_rust(tmp_path: Path) -> Path:
    subprocess.run(
        ["make", "generate-plugins", f"OUT={tmp_path}", "LANGUAGES=rust"],
        cwd=REPO,
        check=True,
        capture_output=True,
    )
    return tmp_path / "o2-scalpel-rust" / "hooks" / "verify-scalpel-rust.sh"


def test_hook_passes_when_lsp_present(tmp_path) -> None:
    hook = _generate_rust(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "rust-analyzer"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"}
    result = subprocess.run(
        [str(hook)], env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "rust-analyzer ready" in result.stdout
    assert "language=rust" in result.stdout


def test_hook_fails_when_lsp_missing(tmp_path) -> None:
    hook = _generate_rust(tmp_path)
    env = {"PATH": "/nonexistent"}
    result = subprocess.run(
        [str(hook)], env=env, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "not found on PATH" in result.stderr
    # Per-language install hint surfaced for rust.
    assert "rustup" in result.stderr


def test_hook_install_hint_exact_for_rust(tmp_path) -> None:
    hook = _generate_rust(tmp_path)
    env = {"PATH": "/nonexistent"}
    result = subprocess.run(
        [str(hook)], env=env, capture_output=True, text=True
    )
    assert "rustup component add rust-analyzer" in result.stderr
