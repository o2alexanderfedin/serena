"""Coverage gate for the v1.9.8 plugin-tree expansion.

The v1.9.8 milestone added eleven new ``LanguageStrategy`` rows to the
generator's metadata table (``serena.refactoring.cli_newplugin._LANGUAGE_METADATA``):
``haxe``, ``erlang``, ``ocaml``, ``powershell``, ``systemverilog``, ``clojure``,
``crystal``, ``elixir``, ``haskell``, ``perl`` and ``ruby``.

Each row must round-trip through :func:`serena.refactoring.cli_newplugin._resolve_strategy`
and the :class:`PluginGenerator` so that ``make generate-plugins`` emits a
well-formed ``o2-scalpel-<lang>/`` tree without falling back to a stub. This
test is the canonical drift-CI gate: if anyone deletes or renames a row,
this file fails before the plugin tree goes stale on disk.

The test also asserts that the v1.9.8 newcomers carry a fresh entry in the
``_INSTALL_HINTS`` dict so the SessionStart hook prints a real install
command (rather than the generic "see plugin README" fallback).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from serena.refactoring.cli_newplugin import _LANGUAGE_METADATA, _resolve_strategy
from serena.refactoring.plugin_generator import _INSTALL_HINTS, PluginGenerator

# Ordered to match the v1.9.8 milestone description so a future leaf can
# slot in by appending rather than reordering.
V1_9_8_NEW_LANGUAGES: tuple[str, ...] = (
    "haxe",
    "erlang",
    "ocaml",
    "powershell",
    "systemverilog",
    "clojure",
    "crystal",
    "elixir",
    "haskell",
    "perl",
    "ruby",
)


@pytest.mark.parametrize("language", V1_9_8_NEW_LANGUAGES)
def test_v1_9_8_language_resolves(language: str) -> None:
    """Every v1.9.8 newcomer must be present in ``_LANGUAGE_METADATA``."""

    strategy = _resolve_strategy(language)
    assert strategy.language == language
    assert strategy.display_name  # non-empty
    assert strategy.file_extensions  # at least one ext
    assert strategy.lsp_server_cmd  # at least one cmd token
    assert strategy.facades  # at least one facade


@pytest.mark.parametrize("language", V1_9_8_NEW_LANGUAGES)
def test_v1_9_8_language_has_install_hint(language: str) -> None:
    """SessionStart hook needs a real install hint for every new language."""

    assert language in _INSTALL_HINTS, (
        f"Add an _INSTALL_HINTS entry for {language!r} in "
        "serena.refactoring.plugin_generator (otherwise the SessionStart hook "
        "falls back to the generic 'see plugin README' string)."
    )
    hint = _INSTALL_HINTS[language]
    assert hint.strip(), f"Install hint for {language!r} must be non-empty."


@pytest.mark.parametrize("language", V1_9_8_NEW_LANGUAGES)
def test_v1_9_8_emit_round_trip(language: str, tmp_path: Path) -> None:
    """End-to-end: ``PluginGenerator().emit`` produces a complete tree.

    Asserts the four invariants every plugin tree must satisfy:
    1. ``.claude-plugin/plugin.json`` parses + advertises the expected name.
    2. ``.mcp.json`` parses + registers an ``mcpServers.lsp`` entry whose
       ``--server-name`` CLI arg is ``scalpel-<lang>`` (v2.0 wire-name
       cleanup — spec 2026-05-03 § 5.2).
    3. ``hooks/hooks.json`` parses + binds the verify script to SessionStart.
    4. At least one ``skills/using-*-<lang>.md`` lands (v2.0 dropped the
       ``scalpel-`` infix from the skill filename pattern).
    """

    strategy = _resolve_strategy(language)
    root = PluginGenerator().emit(strategy, tmp_path)

    plugin_json = json.loads(
        (root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert plugin_json["name"] == f"o2-scalpel-{language}"
    assert plugin_json["category"] == "development"
    assert language in plugin_json["tags"]

    mcp_json = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))
    # v2.0: server JSON-key collapses to "lsp" across all 52 plugins.
    assert "lsp" in mcp_json["mcpServers"], mcp_json
    # v2.0: --server-name CLI arg stays per-language for dashboard pgrep.
    args = mcp_json["mcpServers"]["lsp"]["args"]
    assert "--server-name" in args
    assert args[args.index("--server-name") + 1] == f"scalpel-{language}"

    hooks_json = json.loads(
        (root / "hooks" / "hooks.json").read_text(encoding="utf-8")
    )
    session_start = hooks_json["hooks"]["SessionStart"]
    assert session_start, "SessionStart hooks list must be non-empty"

    skill_files = list((root / "skills").glob(f"using-*-{language}.md"))
    assert skill_files, f"No skill files emitted for {language!r}"
    assert len(skill_files) == len(strategy.facades)


def test_v1_9_8_languages_are_distinct_from_existing() -> None:
    """Catches accidental duplicate registration.

    The newcomers must not collide with the eleven v1.4.1 baseline languages
    (rust/python/markdown/typescript/go/cpp/java/lean/smt2/prolog/problog/csharp).
    """

    pre_v1_9_8 = {
        "rust",
        "python",
        "markdown",
        "typescript",
        "go",
        "cpp",
        "java",
        "lean",
        "smt2",
        "prolog",
        "problog",
        "csharp",
    }
    overlap = pre_v1_9_8.intersection(V1_9_8_NEW_LANGUAGES)
    assert not overlap, f"v1.9.8 newcomer collides with existing language(s): {overlap}"


def test_v1_9_8_metadata_table_has_all_languages() -> None:
    """Sanity: the metadata table must contain every documented language.

    Includes the eleven pre-v1.9.8 languages PLUS the eleven v1.9.8 newcomers.
    v1.14 adds 29 engine-only primaries on top, bringing the table to 52 rows
    — matches the parent ``marketplace.json`` plugin count. The assertion is
    ``actual >= expected`` so future leaves can append without touching this
    test.
    """

    expected = {
        # pre-v1.9.8
        "rust", "python", "markdown", "typescript", "go", "cpp", "java",
        "lean", "smt2", "prolog", "problog", "csharp",
        # v1.9.8 newcomers
        *V1_9_8_NEW_LANGUAGES,
    }
    actual = set(_LANGUAGE_METADATA.keys())
    assert actual >= expected, (
        f"Metadata table missing languages: {expected - actual}"
    )
