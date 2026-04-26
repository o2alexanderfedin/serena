"""Stage 1J T7 — ``_render_session_start_hook`` emits LSP probe shell."""

from __future__ import annotations

from serena.refactoring.plugin_generator import _render_session_start_hook


def test_hook_is_posix_sh(fake_strategy_rust) -> None:
    out = _render_session_start_hook(fake_strategy_rust)
    assert out.startswith("#!/bin/sh\n")


def test_hook_checks_lsp_command(fake_strategy_rust) -> None:
    out = _render_session_start_hook(fake_strategy_rust)
    assert "command -v rust-analyzer" in out


def test_hook_exits_nonzero_on_missing(fake_strategy_rust) -> None:
    out = _render_session_start_hook(fake_strategy_rust)
    assert "exit 1" in out


def test_hook_python(fake_strategy_python) -> None:
    out = _render_session_start_hook(fake_strategy_python)
    assert "command -v pylsp" in out


def test_hook_carries_install_hint_for_known_languages(fake_strategy_rust) -> None:
    out = _render_session_start_hook(fake_strategy_rust)
    assert "rustup" in out
