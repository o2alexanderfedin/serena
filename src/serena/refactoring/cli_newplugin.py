"""Stage 1J ``o2-scalpel-newplugin`` CLI entry point.

Generates a Claude Code plugin tree at ``--out / o2-scalpel-<lang>/``
for the given ``--language``. The strategy resolver is split out as
:func:`_resolve_strategy` so tests can monkey-patch it without touching
the registry.

Stream 5 / Leaf 01 Task 4 added the opt-in ``--repo-root`` flag: when
supplied, the generator regenerates the parent ``marketplace.json`` after
the plugin tree write so the unified manifest stays in lockstep with the
trees it lists. Drift-CI gates the file, so any plugin emit that forgets
``--repo-root`` is caught at CI time.

v1.2 reconciliation collapsed the previous ``marketplace.surface.json``
(schema-driven, engine-internal) into the boostvolt-shape
``marketplace.json``: the refresh hook now writes a single file, sourced
from per-plugin ``plugin.json`` metadata.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from serena.refactoring.plugin_generator import PluginGenerator


@dataclass(frozen=True)
class _Facade:
    """Generator-shape facade entry."""

    name: str
    summary: str
    trigger_phrases: tuple[str, ...]
    primitive_chain: tuple[str, ...]


@dataclass(frozen=True)
class _StrategyView:
    """Adapter exposing the metadata the Stage 1J generator needs.

    The Stage 1E ``LanguageStrategy`` Protocol only carries the LSP wiring
    surface (``language_id``, ``extension_allow_list``, ``build_servers``);
    it does not yet expose display name, server command, or facade lists
    that the plugin generator templates consume. We bridge that gap with
    a per-language metadata table here. Stage 1H/1K may merge this back
    into the strategy Protocol once the FacadeRouter lands.
    """

    language: str
    display_name: str
    file_extensions: tuple[str, ...]
    lsp_server_cmd: tuple[str, ...]
    facades: tuple[_Facade, ...] = field(default_factory=tuple)


# Per-language metadata table. Add a row + verify the smoke goldens (T10)
# whenever a new ``LanguageStrategy`` is registered.
_LANGUAGE_METADATA: dict[str, _StrategyView] = {
    "rust": _StrategyView(
        language="rust",
        display_name="Rust",
        file_extensions=(".rs",),
        lsp_server_cmd=("rust-analyzer",),
        facades=(
            _Facade(
                name="split_file",
                summary="Split a file along symbol boundaries",
                trigger_phrases=("split this file", "extract symbols"),
                primitive_chain=(
                    "textDocument/codeAction",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
        ),
    ),
    "python": _StrategyView(
        language="python",
        display_name="Python",
        file_extensions=(".py", ".pyi"),
        lsp_server_cmd=("pylsp",),
        facades=(
            _Facade(
                name="split_file",
                summary="Split a Python module along symbol boundaries",
                trigger_phrases=("split module", "extract symbols"),
                primitive_chain=(
                    "textDocument/codeAction",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
        ),
    ),
    "markdown": _StrategyView(
        # v1.1.1 Leaf 01: marksman ``server`` subcommand drives the LSP over
        # stdio. The four facades below are the contract Leaf 02 will
        # implement (``ScalpelRenameHeadingTool``, ``ScalpelSplitDocTool``,
        # ``ScalpelExtractSectionTool``, ``ScalpelOrganizeLinksTool``); this
        # row only declares them so the plugin generator can render the
        # marketplace + skill trees ahead of facade-class wiring.
        language="markdown",
        display_name="Markdown",
        file_extensions=(".md", ".markdown", ".mdx"),
        lsp_server_cmd=("marksman", "server"),
        facades=(
            _Facade(
                name="rename_heading",
                summary="Rename a heading and update all cross-file wiki-links",
                trigger_phrases=("rename heading", "refactor heading"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="split_doc",
                summary="Split a long markdown doc along H1/H2 boundaries into linked sub-docs",
                trigger_phrases=("split this doc", "split markdown"),
                primitive_chain=(
                    "textDocument/documentSymbol",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="extract_section",
                summary="Extract a section into a new file with a back-link",
                trigger_phrases=("extract section", "extract heading"),
                primitive_chain=(
                    "textDocument/documentSymbol",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="organize_links",
                summary="Sort and normalize markdown links/wiki-links",
                trigger_phrases=("organize links", "sort links"),
                primitive_chain=(
                    "textDocument/documentLink",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
}


def _resolve_strategy(language: str) -> Any:
    """Resolve the generator-shape view for ``language``.

    Returns a :class:`_StrategyView` (not the raw ``LanguageStrategy`` class)
    because the Stage 1E Protocol does not yet carry display name / server
    command / facade list. Raises :class:`KeyError` if the language is
    unknown.
    """

    if language not in _LANGUAGE_METADATA:
        raise KeyError(language)
    return _LANGUAGE_METADATA[language]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="o2-scalpel-newplugin",
        description="Generate an o2-scalpel-<lang>/ Claude Code plugin tree.",
    )
    p.add_argument(
        "--language",
        required=True,
        help="Target language (e.g. rust, python).",
    )
    p.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output parent directory.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing plugin tree at the target path.",
    )
    p.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help=(
            "Parent o2-scalpel repo root. When supplied, marketplace.json "
            "is regenerated under this directory in the same run as the "
            "plugin tree write. Drift-CI requires the regenerated "
            "marketplace.json to land in the same commit as the plugin-tree "
            "change — otherwise the gate fails."
        ),
    )
    return p


def _refresh_marketplace_surface(repo_root: Path) -> None:
    """Regenerate ``<repo_root>/marketplace.json`` from plugin trees.

    Imports the marketplace builder lazily so a ``serena.refactoring`` import
    doesn't pull the marketplace package eagerly (cheap layering hygiene).

    Function name preserved for backward call-site compatibility; the file
    written is now the unified ``marketplace.json`` (v1.2 reconciliation
    collapsed the previous parallel ``marketplace.surface.json``).
    """

    from serena.marketplace.build import (
        _resolve_engine_sha,
        build_manifest,
        write_manifest,
    )

    manifest = build_manifest(repo_root, generator_sha=_resolve_engine_sha())
    write_manifest(repo_root, manifest)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        strategy = _resolve_strategy(args.language)
    except KeyError:
        print(f"error: unknown language {args.language!r}", file=sys.stderr)
        return 2
    try:
        root = PluginGenerator().emit(strategy, args.out, force=args.force)
    except FileExistsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    if args.repo_root is not None:
        _refresh_marketplace_surface(args.repo_root)
    print(f"wrote {root}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
