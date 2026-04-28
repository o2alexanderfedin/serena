"""Stage 1J T7 — ``_render_session_start_hook`` + ``_render_hooks_json`` emits LSP probe shell + binding."""

from __future__ import annotations

import json

from serena.refactoring.plugin_generator import _render_hooks_json, _render_session_start_hook


def test_hook_is_posix_sh(fake_strategy_rust) -> None:
    out = _render_session_start_hook(fake_strategy_rust)
    assert out.startswith("#!/bin/sh\n")


def test_hook_checks_lsp_command(fake_strategy_rust) -> None:
    out = _render_session_start_hook(fake_strategy_rust)
    assert "command -v rust-analyzer" in out


def test_hook_exits_nonzero_on_missing(fake_strategy_rust) -> None:
    """Hook must use exit 2 (blocking) not exit 1 (warning) — install-mechanics §5."""
    out = _render_session_start_hook(fake_strategy_rust)
    assert "exit 2" in out
    assert "exit 1" not in out


def test_hook_python(fake_strategy_python) -> None:
    out = _render_session_start_hook(fake_strategy_python)
    assert "command -v pylsp" in out


def test_hook_carries_install_hint_for_known_languages(fake_strategy_rust) -> None:
    out = _render_session_start_hook(fake_strategy_rust)
    assert "rustup" in out


# --- § 3.2: hooks.json binding (install-blockers Phase 0) --------------------


def test_hooks_json_has_session_start_binding(fake_strategy_rust) -> None:
    """§ 3.2: hooks.json must exist and bind verify script to SessionStart."""
    out = _render_hooks_json(fake_strategy_rust)
    data = json.loads(out)
    assert "SessionStart" in data["hooks"]


def test_hooks_json_command_points_at_verify_script(fake_strategy_rust) -> None:
    """§ 3.2: command must reference ${CLAUDE_PLUGIN_ROOT}/hooks/verify-scalpel-rust.sh."""
    out = _render_hooks_json(fake_strategy_rust)
    data = json.loads(out)
    entries = data["hooks"]["SessionStart"]
    commands = [h["command"] for block in entries for h in block["hooks"]]
    assert any("verify-scalpel-rust.sh" in cmd for cmd in commands)
    assert any("${CLAUDE_PLUGIN_ROOT}" in cmd for cmd in commands)


def test_hooks_json_type_is_command(fake_strategy_rust) -> None:
    """§ 3.2: hook type field must be 'command'."""
    out = _render_hooks_json(fake_strategy_rust)
    data = json.loads(out)
    entries = data["hooks"]["SessionStart"]
    types = [h["type"] for block in entries for h in block["hooks"]]
    assert all(t == "command" for t in types)


def test_hooks_json_for_python_uses_python_script(fake_strategy_python) -> None:
    """§ 3.2: hooks.json applies uniformly for all languages."""
    out = _render_hooks_json(fake_strategy_python)
    data = json.loads(out)
    entries = data["hooks"]["SessionStart"]
    commands = [h["command"] for block in entries for h in block["hooks"]]
    assert any("verify-scalpel-python.sh" in cmd for cmd in commands)


def test_hooks_json_ends_with_newline(fake_strategy_rust) -> None:
    out = _render_hooks_json(fake_strategy_rust)
    assert out.endswith("\n")
