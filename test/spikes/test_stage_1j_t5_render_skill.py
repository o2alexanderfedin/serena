"""Stage 1J T5 — ``_render_skill_for_facade`` emits per-facade skill md."""

from __future__ import annotations

from serena.refactoring.plugin_generator import _render_skill_for_facade


def test_skill_has_yaml_frontmatter(fake_strategy_rust) -> None:
    facade = fake_strategy_rust.facades[0]  # split_file
    out = _render_skill_for_facade(fake_strategy_rust, facade)
    assert out.startswith("---\n")
    # v2.0 wire-name cleanup (spec 2026-05-03 § 5.1): the ``scalpel-`` infix
    # was dropped from skill filenames to match the unprefixed tool name.
    assert "name: using-split-file-rust\n" in out
    assert "type: skill\n" in out
    assert "description:" in out


def test_skill_body_lists_trigger_phrases(fake_strategy_rust) -> None:
    facade = fake_strategy_rust.facades[0]
    out = _render_skill_for_facade(fake_strategy_rust, facade)
    assert "## When to use" in out
    assert "split this file" in out
    assert "extract symbols" in out


def test_skill_body_lists_primitive_chain(fake_strategy_rust) -> None:
    facade = fake_strategy_rust.facades[0]
    out = _render_skill_for_facade(fake_strategy_rust, facade)
    assert "## How it works" in out
    assert "textDocument/codeAction" in out
    assert "workspace/applyEdit" in out


def test_skill_for_python(fake_strategy_python) -> None:
    facade = fake_strategy_python.facades[0]
    out = _render_skill_for_facade(fake_strategy_python, facade)
    # v2.0: ``scalpel-`` infix dropped (spec 2026-05-03 § 5.1).
    assert "name: using-split-file-python\n" in out


def test_skill_is_deterministic(fake_strategy_rust) -> None:
    facade = fake_strategy_rust.facades[0]
    a = _render_skill_for_facade(fake_strategy_rust, facade)
    b = _render_skill_for_facade(fake_strategy_rust, facade)
    assert a == b
