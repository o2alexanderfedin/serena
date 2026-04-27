"""Walk a parent repo root and emit a :class:`MarketplaceManifest`.

The published o2-scalpel layout has language plugins as direct children of
the parent repo root (``o2-scalpel-rust/``, ``o2-scalpel-python/``) rather
than nested under a ``plugins/`` directory. The walker therefore globs for
``o2-scalpel-*/.claude-plugin/plugin.json`` from the repo root. See the
leaf brief's path-correction note (a) — this is a deliberate deviation
from the spec's example pseudocode.

Per-plugin language is derived from the ``.mcp.json``'s ``--language`` arg
when present (the canonical signal emitted by the Stage 1J generator), with
a fallback to the directory name's ``o2-scalpel-<lang>`` suffix. The
install hint is looked up in the same per-language table the plugin
generator uses.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from serena.marketplace.schema import MarketplaceManifest, PluginEntry

# Per-language LSP install hints. Mirrors the table at
# ``serena.refactoring.plugin_generator._INSTALL_HINTS`` so a single change
# in either layer surfaces as drift in ``marketplace.json``. We don't import
# the constant directly to keep ``serena.marketplace`` free of refactoring
# imports — it's a strict-leaf publication surface, not an LSP module.
_INSTALL_HINTS: dict[str, str] = {
    "rust": "rustup component add rust-analyzer",
    "python": "pipx install python-lsp-server",
    "typescript": "npm i -g typescript-language-server typescript",
    "go": "go install golang.org/x/tools/gopls@latest",
}

_PLUGIN_DIR_PREFIX = "o2-scalpel-"


def _language_from_mcp_json(mcp_json_path: Path) -> str | None:
    """Return the ``--language`` value from a ``.mcp.json``, or ``None``."""

    try:
        payload = json.loads(mcp_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    servers = payload.get("mcpServers")
    if not isinstance(servers, dict):
        return None
    for spec in servers.values():
        if not isinstance(spec, dict):
            continue
        args = spec.get("args")
        if not isinstance(args, list):
            continue
        # ``--language`` is followed by its value in argv-style flags.
        for idx, item in enumerate(args[:-1]):
            if item == "--language" and isinstance(args[idx + 1], str):
                return args[idx + 1]
    return None


def _language_from_dirname(dir_name: str) -> str:
    """Strip the ``o2-scalpel-`` prefix to recover the language id."""

    return dir_name[len(_PLUGIN_DIR_PREFIX):]


def _entry_for(plugin_dir: Path) -> PluginEntry:
    """Build one :class:`PluginEntry` from a plugin tree."""

    plugin_json = plugin_dir / ".claude-plugin" / "plugin.json"
    data = json.loads(plugin_json.read_text(encoding="utf-8"))
    language = _language_from_mcp_json(plugin_dir / ".mcp.json") or _language_from_dirname(
        plugin_dir.name
    )
    install_hint = _INSTALL_HINTS.get(language, "")
    return PluginEntry(
        id=plugin_dir.name,
        name=data["name"],
        language=language,
        path=plugin_dir.name,
        version=data["version"],
        install_hint=install_hint,
    )


def build_manifest(repo_root: Path) -> MarketplaceManifest:
    """Walk ``repo_root`` for ``o2-scalpel-*`` plugin trees.

    :param repo_root: parent o2-scalpel repository root containing one or more
        ``o2-scalpel-<language>/`` plugin trees with ``.claude-plugin/plugin.json``.
    :return: a frozen :class:`MarketplaceManifest`. Entries are sorted by id
        so the generator output is byte-identical regardless of filesystem
        iteration order — the drift-CI gate depends on this determinism.
    """

    entries: list[PluginEntry] = []
    if not repo_root.is_dir():
        return MarketplaceManifest(plugins=())
    for sub in sorted(repo_root.iterdir(), key=lambda p: p.name):
        if not sub.is_dir() or not sub.name.startswith(_PLUGIN_DIR_PREFIX):
            continue
        if not (sub / ".claude-plugin" / "plugin.json").is_file():
            continue
        entries.append(_entry_for(sub))
    return MarketplaceManifest(plugins=tuple(entries))


def render_manifest_json(manifest: MarketplaceManifest) -> str:
    """Render a :class:`MarketplaceManifest` to canonical JSON.

    The ``sort_keys=True`` + ``indent=2`` + trailing newline format matches
    the convention used elsewhere in the engine (capability catalog, plugin
    generator), giving the drift-CI gate a byte-identical comparison target.
    """

    return (
        json.dumps(manifest.model_dump(), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    )


SURFACE_FILENAME = "marketplace.surface.json"
"""On-disk filename for the schema-driven publication-surface descriptor.

Distinct from the existing parent-root ``marketplace.json`` (boostvolt-shape,
Claude-Code-marketplace consumer-facing artifact emitted by Stage 1I's
``serena.refactoring.cli_newplugin_marketplace`` path). The two files coexist:
this leaf adds the schema-driven internal surface gated by drift-CI, while
the boostvolt-shape file remains the consumer-facing publication artifact.
"""


def write_manifest(repo_root: Path, manifest: MarketplaceManifest) -> Path:
    """Write ``manifest`` to ``<repo_root>/marketplace.surface.json``.

    Returns the path written. The same code path is used by the drift-CI
    re-baseline command (``--write``) and by the ``cli_newplugin`` integration
    that updates the surface file after each plugin emit.
    """

    payload = render_manifest_json(manifest)
    out = repo_root / SURFACE_FILENAME
    out.write_text(payload, encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    """``python -m serena.marketplace.build`` entry point.

    Without ``--write`` the rendered JSON goes to stdout; with ``--write`` it
    is persisted to ``<root>/marketplace.surface.json``. The drift-CI gate
    uses the no-flag form to compare against the on-disk golden.
    """

    parser = argparse.ArgumentParser(
        prog="serena.marketplace.build",
        description=(
            "Build the o2-scalpel publication-surface manifest "
            "(marketplace.surface.json) from plugin trees under --root."
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Parent repo root to scan (default: cwd).",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"Persist the manifest to <root>/{SURFACE_FILENAME}.",
    )
    args = parser.parse_args(argv)
    manifest = build_manifest(args.root)
    if args.write:
        write_manifest(args.root, manifest)
    else:
        sys.stdout.write(render_manifest_json(manifest))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "SURFACE_FILENAME",
    "build_manifest",
    "main",
    "render_manifest_json",
    "write_manifest",
]
