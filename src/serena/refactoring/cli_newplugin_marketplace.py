"""Companion CLI: emit only ``marketplace.json`` for a list of languages.

This sister of ``cli_newplugin`` writes a single aggregator file at
``--out / marketplace.json`` referencing one ``./o2-scalpel-<lang>/``
entry per language passed positionally. Used by ``make generate-plugins``
after looping the per-language plugin generator.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from serena.refactoring.cli_newplugin import _resolve_strategy
from serena.refactoring.plugin_generator import _render_marketplace_json


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="o2-scalpel-marketplace",
        description="Emit only marketplace.json for the given languages.",
    )
    p.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output directory; marketplace.json is written here.",
    )
    p.add_argument(
        "languages",
        nargs="+",
        help="Languages to include (e.g. rust python).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    strategies = [_resolve_strategy(lang) for lang in args.languages]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "marketplace.json").write_text(
        _render_marketplace_json(strategies), encoding="utf-8"
    )
    print(f"wrote {args.out / 'marketplace.json'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
