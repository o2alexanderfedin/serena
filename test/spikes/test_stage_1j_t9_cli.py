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


# Stream 5 / Leaf 01 Task 4 + v1.2 reconciliation — marketplace.json refresh.


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


def test_main_refreshes_unified_marketplace_when_repo_root_set(
    tmp_path, monkeypatch, fake_strategy_rust
) -> None:
    """When ``--repo-root`` is passed, ``marketplace.json`` is regenerated.

    v1.2 reconciliation collapsed the previous parallel
    ``marketplace.surface.json`` into the unified boostvolt-shape
    ``marketplace.json``; the refresh hook now writes a single file that
    lists the freshly-emitted plugin tree with the rich marketplace-UI
    metadata read from the per-plugin ``plugin.json``. Drift-CI requires
    the regenerated ``marketplace.json`` to land in the same commit as
    any plugin-tree change, so the CLI updates it atomically.
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
    surface = tmp_path / "marketplace.json"
    assert surface.exists()
    payload = json.loads(surface.read_text(encoding="utf-8"))
    names = [p["name"] for p in payload["plugins"]]
    assert "o2-scalpel-rust" in names
    # Surface file no longer written.
    assert not (tmp_path / "marketplace.surface.json").exists()


def test_main_skips_marketplace_refresh_when_repo_root_omitted(
    tmp_path, monkeypatch, fake_strategy_rust
) -> None:
    """Without ``--repo-root`` no marketplace file is touched.

    Running the generator into an arbitrary ``--out`` directory must not
    create a ``marketplace.json`` (or the legacy ``marketplace.surface.json``)
    there; that's a deliberate opt-in via ``--repo-root`` so existing
    callers (and the smoke goldens that snapshot the per-plugin tree)
    don't see new files.
    """

    from serena.refactoring import cli_newplugin

    monkeypatch.setattr(
        cli_newplugin, "_resolve_strategy", lambda _lang: fake_strategy_rust
    )
    rc = main(["--language", "rust", "--out", str(tmp_path)])
    assert rc == 0
    assert not (tmp_path / "marketplace.json").exists()
    assert not (tmp_path / "marketplace.surface.json").exists()


def test_help_documents_repo_root_same_commit_rule(capsys) -> None:
    """``--help`` must surface the same-commit rule (per spec Task 4 step 4.2)."""

    parser = build_parser()
    help_text = parser.format_help()
    assert "--repo-root" in help_text
    assert "marketplace.json" in help_text
