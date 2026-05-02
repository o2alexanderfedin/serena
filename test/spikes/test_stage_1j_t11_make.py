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


def test_make_generate_plugins_marketplace_lists_every_emitted_tree(tmp_path) -> None:
    """The marketplace.json aggregator must list every o2-scalpel-<lang>/
    tree the generator wrote — and nothing else. Self-discovering against
    the Makefile's LANGUAGES default so adding a language doesn't require
    touching this assertion (was the v1.4.1 + v1.10 stale-12 problem)."""
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
    marketplace_names = sorted(p["name"] for p in data["plugins"])
    emitted_dirs = sorted(
        p.name for p in tmp_path.iterdir()
        if p.is_dir() and p.name.startswith("o2-scalpel-")
    )
    assert marketplace_names == emitted_dirs, (
        f"marketplace.json plugin list out of sync with emitted trees:\n"
        f"  marketplace lists: {marketplace_names}\n"
        f"  generator wrote:   {emitted_dirs}"
    )
    # Sanity floor: at least the rust + python anchors used in other tests.
    assert "o2-scalpel-rust" in marketplace_names
    assert "o2-scalpel-python" in marketplace_names
