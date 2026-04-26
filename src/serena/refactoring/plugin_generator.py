"""Stage 1J plugin generator — emits ``o2-scalpel-<lang>/`` Claude Code plugin trees.

The generator composes six small ``_render_*`` helpers, each backed by a
pydantic v2 schema and (where applicable) a ``string.Template`` source under
``./templates/``, into a deterministic byte-identical filesystem write rooted
at ``out_parent / o2-scalpel-<language>/``.

Public surface:

* :class:`PluginGenerator` — composition root.
* ``_render_plugin_json(strategy)``
* ``_render_mcp_json(strategy)``
* ``_render_marketplace_json(strategies)``
* ``_render_skill_for_facade(strategy, facade)``
* ``_render_readme(strategy)``
* ``_render_session_start_hook(strategy)``

All emitted JSON uses ``sort_keys=True, indent=2, ensure_ascii=False`` and
ends in a trailing newline (POSIX). All shell scripts are POSIX ``sh``.
"""

from __future__ import annotations

import json
from typing import Protocol

from serena.refactoring.plugin_schemas import AuthorInfo, PluginManifest

# Identity constants for every emitted plugin. Kept module-private so they
# travel with the generator and are easy to lift to env in Stage 1K if we
# ever want to publish plugins under a different owner.
_AUTHOR = "AI Hive(R)"
_LICENSE = "MIT"
_REPO = "https://github.com/o2services/o2-scalpel"
_VERSION = "1.0.0"


class _StrategyLike(Protocol):
    """Structural subset of ``LanguageStrategy`` the generator depends on."""

    language: str
    display_name: str
    file_extensions: tuple[str, ...]
    lsp_server_cmd: tuple[str, ...]


def _plugin_name(strategy: _StrategyLike) -> str:
    return f"o2-scalpel-{strategy.language}"


def _description(strategy: _StrategyLike) -> str:
    cmd = strategy.lsp_server_cmd[0]
    return f"Scalpel refactor MCP server for {strategy.display_name} via {cmd}"


def _render_plugin_json(strategy: _StrategyLike) -> str:
    """Render the boostvolt-shape ``.claude-plugin/plugin.json``."""

    manifest = PluginManifest(
        name=_plugin_name(strategy),
        description=_description(strategy),
        version=_VERSION,
        author=AuthorInfo(name=_AUTHOR),
        license=_LICENSE,
        repository=_REPO,
        homepage=_REPO,
    )
    payload = manifest.model_dump(mode="json", by_alias=True)
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


__all__ = [
    "PluginManifest",  # re-export for callers
    "_render_plugin_json",
]
