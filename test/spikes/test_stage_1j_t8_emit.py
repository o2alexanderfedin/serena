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
    # v2.0 wire-name cleanup (spec 2026-05-03 § 5.1): skill filenames drop
    # the ``scalpel-`` infix to match the unprefixed v2.0 tool name.
    assert (root / "skills" / "using-split-file-rust.md").exists()
    assert (root / "skills" / "using-rename-symbol-rust.md").exists()


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
    # v2.0: ``scalpel-`` infix dropped (spec 2026-05-03 § 5.1).
    assert (root / "skills" / "using-split-file-python.md").exists()


# --- § 3.2: emit must write hooks.json alongside verify-scalpel-*.sh --------


def test_emit_writes_hooks_json(tmp_path, fake_strategy_rust) -> None:
    """§ 3.2: emit must produce hooks/hooks.json binding the verify script."""
    PluginGenerator().emit(fake_strategy_rust, tmp_path)
    assert (tmp_path / "o2-scalpel-rust" / "hooks" / "hooks.json").exists()


def test_emit_hooks_json_has_session_start(tmp_path, fake_strategy_rust) -> None:
    """§ 3.2: hooks.json must bind verify script to SessionStart."""
    PluginGenerator().emit(fake_strategy_rust, tmp_path)
    data = json.loads(
        (tmp_path / "o2-scalpel-rust" / "hooks" / "hooks.json").read_text()
    )
    assert "SessionStart" in data["hooks"]


# --- v1.10: emit must write commands/<plugin>-dashboard.md slash command ----


def test_emit_writes_dashboard_command(tmp_path, fake_strategy_rust) -> None:
    """v1.10: every plugin tree ships a /<plugin>-dashboard slash command."""
    PluginGenerator().emit(fake_strategy_rust, tmp_path)
    cmd = (
        tmp_path
        / "o2-scalpel-rust"
        / "commands"
        / "o2-scalpel-rust-dashboard.md"
    )
    assert cmd.exists()


def test_emit_dashboard_command_targets_plugin_server_name(
    tmp_path, fake_strategy_rust
) -> None:
    """The slash-command body must pin to the plugin's MCP server-name so a
    /o2-scalpel-rust-dashboard call only opens the rust dashboard, not any
    co-running scalpel-python or scalpel-markdown instance."""
    PluginGenerator().emit(fake_strategy_rust, tmp_path)
    body = (
        tmp_path
        / "o2-scalpel-rust"
        / "commands"
        / "o2-scalpel-rust-dashboard.md"
    ).read_text()
    # The discovery regex pins on --server-name scalpel-rust.
    assert "--server-name scalpel-rust" in body
    # The slash command name in the heading matches the plugin name.
    assert "/o2-scalpel-rust-dashboard" in body


def test_emit_dashboard_command_for_python(
    tmp_path, fake_strategy_python
) -> None:
    """Per-language naming holds for any plugin, not just rust."""
    PluginGenerator().emit(fake_strategy_python, tmp_path)
    cmd = (
        tmp_path
        / "o2-scalpel-python"
        / "commands"
        / "o2-scalpel-python-dashboard.md"
    )
    assert cmd.exists()
    body = cmd.read_text()
    assert "--server-name scalpel-python" in body
    assert "/o2-scalpel-python-dashboard" in body


# --- v1.11: emit must write the engine-global /o2-scalpel-update slash command
# and the SessionStart check-update + statusline scripts ---------------------


def test_emit_writes_update_command(tmp_path, fake_strategy_rust) -> None:
    """v1.11: every plugin tree ships /o2-scalpel-update at commands/o2-scalpel-update.md."""
    PluginGenerator().emit(fake_strategy_rust, tmp_path)
    cmd = tmp_path / "o2-scalpel-rust" / "commands" / "o2-scalpel-update.md"
    assert cmd.exists()
    body = cmd.read_text()
    # Engine-global: filename has no language suffix, body refers to the
    # canonical engine git URL and the global slash-command name.
    assert "/o2-scalpel-update" in body
    assert "o2-scalpel-engine.git" in body


def test_emit_update_command_is_identical_across_languages(
    tmp_path, fake_strategy_rust, fake_strategy_python
) -> None:
    """The /o2-scalpel-update body must be byte-identical regardless of plugin
    so Claude Code's plugin registry treats them as a single command and the
    user has one stable name to type."""
    PluginGenerator().emit(fake_strategy_rust, tmp_path)
    PluginGenerator().emit(fake_strategy_python, tmp_path)
    rust_body = (
        tmp_path / "o2-scalpel-rust" / "commands" / "o2-scalpel-update.md"
    ).read_text()
    py_body = (
        tmp_path / "o2-scalpel-python" / "commands" / "o2-scalpel-update.md"
    ).read_text()
    assert rust_body == py_body


def test_emit_writes_check_update_hook(tmp_path, fake_strategy_rust) -> None:
    """v1.11: check-scalpel-update.sh ships in every plugin's hooks/ dir."""
    PluginGenerator().emit(fake_strategy_rust, tmp_path)
    hook = tmp_path / "o2-scalpel-rust" / "hooks" / "check-scalpel-update.sh"
    assert hook.exists()
    # Executable bit must be set for SessionStart hook to run.
    assert hook.stat().st_mode & stat.S_IXUSR
    body = hook.read_text()
    assert "git ls-remote" in body
    assert "o2-scalpel-engine.git" in body
    assert "update_available" in body  # writes the cache key


def test_emit_check_update_hook_uses_plugin_data_dir(
    tmp_path, fake_strategy_rust
) -> None:
    """v1.12: cache must live under ${CLAUDE_PLUGIN_DATA}/update-cache so
    Claude Code auto-cleans it on plugin uninstall (research 2026-05-01).
    Legacy ~/.cache/o2-scalpel/ kept only as a fallback when CLAUDE_PLUGIN_DATA
    is unset (ad-hoc invocations outside plugin context)."""
    PluginGenerator().emit(fake_strategy_rust, tmp_path)
    body = (
        tmp_path / "o2-scalpel-rust" / "hooks" / "check-scalpel-update.sh"
    ).read_text()
    assert "${CLAUDE_PLUGIN_DATA}/update-cache" in body
    # Fallback path is still present (script must remain useful when run
    # without Claude Code's env), but the primary path is plugin-data.
    assert body.index("${CLAUDE_PLUGIN_DATA}") < body.index(
        "${HOME}/.cache/o2-scalpel"
    ), "primary path must be CLAUDE_PLUGIN_DATA, fallback after"


def test_emit_writes_statusline_script(tmp_path, fake_strategy_rust) -> None:
    """v1.11: scalpel-statusline.sh ships per-plugin so users can wire any
    plugin's copy into their ~/.claude/settings.json statusLine.command."""
    PluginGenerator().emit(fake_strategy_rust, tmp_path)
    script = (
        tmp_path / "o2-scalpel-rust" / "hooks" / "scalpel-statusline.sh"
    )
    assert script.exists()
    assert script.stat().st_mode & stat.S_IXUSR
    body = script.read_text()
    assert "/o2-scalpel-update" in body
    assert "update-check.json" in body


def test_emit_statusline_glob_falls_back_across_plugins(
    tmp_path, fake_strategy_rust
) -> None:
    """v1.12: statusLine script must be robust to plugin uninstall — the
    fallback glob across ~/.claude/plugins/data/o2-scalpel-*/ ensures the
    script keeps emitting the indicator (or empty) even if THIS plugin is
    uninstalled but another scalpel-* plugin remains installed."""
    PluginGenerator().emit(fake_strategy_rust, tmp_path)
    body = (
        tmp_path / "o2-scalpel-rust" / "hooks" / "scalpel-statusline.sh"
    ).read_text()
    # Primary: read this plugin's CLAUDE_PLUGIN_DATA cache when present.
    assert "${CLAUDE_PLUGIN_DATA}/update-cache" in body
    # Fallback: glob across all installed scalpel-* plugin data dirs.
    assert (
        "/.claude/plugins/data/o2-scalpel-*/update-cache" in body
    ), "statusLine script must fall back to a glob across scalpel-* plugin data dirs"


def test_emit_update_command_clears_all_plugin_caches(
    tmp_path, fake_strategy_rust
) -> None:
    """v1.12: /o2-scalpel-update must update the cache JSON for EVERY enabled
    plugin in one go, not just the one that owns the slash command. Without
    this, the status-line indicator persists for plugins whose cache wasn't
    touched until their next SessionStart fires."""
    PluginGenerator().emit(fake_strategy_rust, tmp_path)
    body = (
        tmp_path / "o2-scalpel-rust" / "commands" / "o2-scalpel-update.md"
    ).read_text()
    # Glob across all plugin-data dirs.
    assert (
        "/.claude/plugins/data/o2-scalpel-*/update-cache" in body
    ), "/o2-scalpel-update must clear all plugins' caches"
    # Legacy migration cleanup.
    assert "rm -rf" in body and "/.cache/o2-scalpel" in body


def test_emit_hooks_json_registers_check_update_hook(
    tmp_path, fake_strategy_rust
) -> None:
    """SessionStart array must include the check-update hook alongside the
    LSP-verify hook, so update detection runs without user opt-in."""
    PluginGenerator().emit(fake_strategy_rust, tmp_path)
    data = json.loads(
        (tmp_path / "o2-scalpel-rust" / "hooks" / "hooks.json").read_text()
    )
    commands = [
        h["command"] for entry in data["hooks"]["SessionStart"]
        for h in entry["hooks"]
    ]
    # Both hooks must be wired.
    assert any("verify-scalpel-rust.sh" in c for c in commands)
    assert any("check-scalpel-update.sh" in c for c in commands)
