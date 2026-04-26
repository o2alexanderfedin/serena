"""Stage 1J T6 — ``_render_readme`` generates per-plugin README.md."""

from __future__ import annotations

from serena.refactoring.plugin_generator import _render_readme


def test_readme_has_title(fake_strategy_rust) -> None:
    out = _render_readme(fake_strategy_rust)
    assert out.startswith("# o2-scalpel-rust")


def test_readme_install_section(fake_strategy_rust) -> None:
    out = _render_readme(fake_strategy_rust)
    assert "## Install" in out
    assert "claude plugin install" in out


def test_readme_lists_all_facades(fake_strategy_rust) -> None:
    out = _render_readme(fake_strategy_rust)
    assert "scalpel_split_file" in out
    assert "scalpel_rename_symbol" in out


def test_readme_mentions_lsp_command(fake_strategy_rust) -> None:
    out = _render_readme(fake_strategy_rust)
    assert "rust-analyzer" in out


def test_readme_mentions_extensions(fake_strategy_rust) -> None:
    out = _render_readme(fake_strategy_rust)
    assert ".rs" in out
