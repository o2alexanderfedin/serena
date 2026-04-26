"""Stage 1J T8 — ``PluginGenerator.emit`` composes the full tree."""

from __future__ import annotations

import json
import stat

import pytest

from serena.refactoring.plugin_generator import PluginGenerator


def test_emit_writes_full_tree(tmp_path, fake_strategy_rust) -> None:
    gen = PluginGenerator()
    gen.emit(fake_strategy_rust, tmp_path)
    root = tmp_path / "o2-scalpel-rust"
    assert (root / ".claude-plugin" / "plugin.json").exists()
    assert (root / ".mcp.json").exists()
    assert (root / "README.md").exists()
    assert (root / "hooks" / "verify-scalpel-rust.sh").exists()
    assert (root / "skills" / "using-scalpel-split-file-rust.md").exists()
    assert (root / "skills" / "using-scalpel-rename-symbol-rust.md").exists()


def test_emit_hook_is_executable(tmp_path, fake_strategy_rust) -> None:
    PluginGenerator().emit(fake_strategy_rust, tmp_path)
    hook = tmp_path / "o2-scalpel-rust" / "hooks" / "verify-scalpel-rust.sh"
    mode = hook.stat().st_mode
    assert mode & stat.S_IXUSR


def test_emit_plugin_json_valid(tmp_path, fake_strategy_rust) -> None:
    PluginGenerator().emit(fake_strategy_rust, tmp_path)
    data = json.loads(
        (tmp_path / "o2-scalpel-rust" / ".claude-plugin" / "plugin.json").read_text()
    )
    assert data["name"] == "o2-scalpel-rust"


def test_emit_refuses_existing_dir_without_force(
    tmp_path, fake_strategy_rust
) -> None:
    (tmp_path / "o2-scalpel-rust").mkdir()
    with pytest.raises(FileExistsError):
        PluginGenerator().emit(fake_strategy_rust, tmp_path)


def test_emit_force_overwrites(tmp_path, fake_strategy_rust) -> None:
    (tmp_path / "o2-scalpel-rust").mkdir()
    (tmp_path / "o2-scalpel-rust" / "stale.txt").write_text("old")
    PluginGenerator().emit(fake_strategy_rust, tmp_path, force=True)
    assert not (tmp_path / "o2-scalpel-rust" / "stale.txt").exists()
    assert (tmp_path / "o2-scalpel-rust" / ".mcp.json").exists()


def test_emit_returns_root_path(tmp_path, fake_strategy_rust) -> None:
    root = PluginGenerator().emit(fake_strategy_rust, tmp_path)
    assert root == tmp_path / "o2-scalpel-rust"


def test_emit_for_python(tmp_path, fake_strategy_python) -> None:
    PluginGenerator().emit(fake_strategy_python, tmp_path)
    root = tmp_path / "o2-scalpel-python"
    assert (root / "skills" / "using-scalpel-split-file-python.md").exists()
