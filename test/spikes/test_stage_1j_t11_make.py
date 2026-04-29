"""Stage 1J T11 — ``make generate-plugins`` regenerates the plugin trees.

This test calls the parent-repo Makefile target and asserts that the
generator emits a complete ``o2-scalpel-rust/`` tree plus a top-level
``marketplace.json`` aggregator.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

# Skip if make is unavailable (e.g. minimal CI containers).
pytestmark = pytest.mark.skipif(
    shutil.which("make") is None, reason="make not installed"
)

REPO = Path(__file__).resolve().parents[4]


def test_make_generate_plugins_creates_rust(tmp_path) -> None:
    result = subprocess.run(
        ["make", "generate-plugins", f"OUT={tmp_path}"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stderr:\n{result.stderr}"
    assert (
        tmp_path / "o2-scalpel-rust" / ".claude-plugin" / "plugin.json"
    ).exists()
    # Post-v1.2.2: marketplace.json lives under .claude-plugin/.
    assert (tmp_path / ".claude-plugin" / "marketplace.json").exists()


def test_make_generate_plugins_includes_python(tmp_path) -> None:
    result = subprocess.run(
        ["make", "generate-plugins", f"OUT={tmp_path}"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stderr:\n{result.stderr}"
    assert (
        tmp_path / "o2-scalpel-python" / ".claude-plugin" / "plugin.json"
    ).exists()


def test_make_generate_plugins_marketplace_lists_both(tmp_path) -> None:
    import json

    result = subprocess.run(
        ["make", "generate-plugins", f"OUT={tmp_path}"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stderr:\n{result.stderr}"
    # Post-v1.2.2: marketplace.json lives under .claude-plugin/.
    data = json.loads(
        (tmp_path / ".claude-plugin" / "marketplace.json").read_text()
    )
    names = sorted(p["name"] for p in data["plugins"])
    # Post-Stream-6 + v1.4.1 expansion: 12 plugins are emitted by default.
    assert names == sorted([
        "o2-scalpel-cpp",
        "o2-scalpel-csharp",
        "o2-scalpel-go",
        "o2-scalpel-java",
        "o2-scalpel-lean",
        "o2-scalpel-markdown",
        "o2-scalpel-prolog",
        "o2-scalpel-problog",
        "o2-scalpel-python",
        "o2-scalpel-rust",
        "o2-scalpel-smt2",
        "o2-scalpel-typescript",
    ])
