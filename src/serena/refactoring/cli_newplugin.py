"""Stage 1J ``o2-scalpel-newplugin`` CLI entry point.

Generates a Claude Code plugin tree at ``--out / o2-scalpel-<lang>/``
for the given ``--language``. The strategy resolver is split out as
:func:`_resolve_strategy` so tests can monkey-patch it without touching
the registry.
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
    return p


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
    print(f"wrote {root}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
