"""Stage 1J T9 — ``o2-scalpel-newplugin`` CLI entry."""

from __future__ import annotations

import pytest

from serena.refactoring.cli_newplugin import build_parser, main


def test_parser_requires_language() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_parser_accepts_force(tmp_path) -> None:
    parser = build_parser()
    ns = parser.parse_args(
        ["--language", "rust", "--out", str(tmp_path), "--force"]
    )
    assert ns.language == "rust"
    assert ns.force is True


def test_main_emits_tree_for_rust(
    tmp_path, monkeypatch, fake_strategy_rust
) -> None:
    from serena.refactoring import cli_newplugin

    monkeypatch.setattr(
        cli_newplugin, "_resolve_strategy", lambda lang: fake_strategy_rust
    )
    rc = main(["--language", "rust", "--out", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "o2-scalpel-rust" / ".claude-plugin" / "plugin.json").exists()


def test_main_unknown_language_errors(
    tmp_path, monkeypatch, capsys
) -> None:
    from serena.refactoring import cli_newplugin

    def _raise(lang: str):
        raise KeyError(lang)

    monkeypatch.setattr(cli_newplugin, "_resolve_strategy", _raise)
    rc = main(["--language", "klingon", "--out", str(tmp_path)])
    assert rc == 2
    assert "unknown language" in capsys.readouterr().err.lower()


def test_main_existing_dir_without_force_errors(
    tmp_path, monkeypatch, fake_strategy_rust, capsys
) -> None:
    from serena.refactoring import cli_newplugin

    monkeypatch.setattr(
        cli_newplugin, "_resolve_strategy", lambda lang: fake_strategy_rust
    )
    (tmp_path / "o2-scalpel-rust").mkdir()
    rc = main(["--language", "rust", "--out", str(tmp_path)])
    assert rc == 3
    assert "error" in capsys.readouterr().err.lower()
