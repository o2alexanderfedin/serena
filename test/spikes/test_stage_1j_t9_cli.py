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
        cli_newplugin, "_resolve_strategy", lambda _lang: fake_strategy_rust
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
        cli_newplugin, "_resolve_strategy", lambda _lang: fake_strategy_rust
    )
    (tmp_path / "o2-scalpel-rust").mkdir()
    rc = main(["--language", "rust", "--out", str(tmp_path)])
    assert rc == 3
    assert "error" in capsys.readouterr().err.lower()


# Stream 5 / Leaf 01 Task 4 — marketplace.surface.json integration.


def test_parser_accepts_repo_root(tmp_path) -> None:
    parser = build_parser()
    ns = parser.parse_args(
        [
            "--language",
            "rust",
            "--out",
            str(tmp_path),
            "--repo-root",
            str(tmp_path),
        ]
    )
    assert ns.repo_root == tmp_path


def test_main_appends_to_marketplace_surface(
    tmp_path, monkeypatch, fake_strategy_rust
) -> None:
    """When ``--repo-root`` is passed, the surface manifest is regenerated.

    The updated ``marketplace.surface.json`` lands at
    ``<repo-root>/marketplace.surface.json`` and lists the freshly-emitted
    plugin tree. Drift-CI requires the surface file to be in the same commit
    as any plugin-tree change, so the CLI now updates it atomically.
    """

    import json

    from serena.refactoring import cli_newplugin

    monkeypatch.setattr(
        cli_newplugin, "_resolve_strategy", lambda _lang: fake_strategy_rust
    )
    rc = main(
        [
            "--language",
            "rust",
            "--out",
            str(tmp_path),
            "--repo-root",
            str(tmp_path),
        ]
    )
    assert rc == 0
    surface = tmp_path / "marketplace.surface.json"
    assert surface.exists()
    payload = json.loads(surface.read_text(encoding="utf-8"))
    ids = [p["id"] for p in payload["plugins"]]
    assert "o2-scalpel-rust" in ids


def test_main_skips_surface_update_when_repo_root_omitted(
    tmp_path, monkeypatch, fake_strategy_rust
) -> None:
    """Without ``--repo-root`` the legacy behaviour is preserved.

    Running the generator into an arbitrary ``--out`` directory must not
    create a ``marketplace.surface.json`` there; that's a deliberate opt-in
    via ``--repo-root`` so existing callers (and the smoke goldens that
    snapshot the per-plugin tree) don't see new files.
    """

    from serena.refactoring import cli_newplugin

    monkeypatch.setattr(
        cli_newplugin, "_resolve_strategy", lambda _lang: fake_strategy_rust
    )
    rc = main(["--language", "rust", "--out", str(tmp_path)])
    assert rc == 0
    assert not (tmp_path / "marketplace.surface.json").exists()


def test_help_documents_repo_root_same_commit_rule(capsys) -> None:
    """``--help`` must surface the same-commit rule (per spec Task 4 step 4.2)."""

    parser = build_parser()
    help_text = parser.format_help()
    assert "--repo-root" in help_text
    assert "marketplace.surface.json" in help_text
