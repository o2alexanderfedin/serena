"""Stage 1J ``o2-scalpel-newplugin`` CLI entry point.

Generates a Claude Code plugin tree at ``--out / o2-scalpel-<lang>/``
for the given ``--language``. The strategy resolver is split out as
:func:`_resolve_strategy` so tests can monkey-patch it without touching
the registry.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from serena.refactoring.plugin_generator import PluginGenerator


def _resolve_strategy(language: str) -> Any:
    """Resolve a ``LanguageStrategy`` for ``language`` via the Stage 1E registry.

    Wired here so tests can monkey-patch a single function instead of the
    whole registry. Raises :class:`KeyError` if the language is unknown.
    """

    from solidlsp.ls_config import Language

    from serena.refactoring import STRATEGY_REGISTRY

    try:
        lang_enum = Language(language)
    except ValueError as exc:
        raise KeyError(language) from exc
    if lang_enum not in STRATEGY_REGISTRY:
        raise KeyError(language)
    return STRATEGY_REGISTRY[lang_enum]


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
