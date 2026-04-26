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
from pathlib import Path
from string import Template
from typing import Protocol

from serena.refactoring.plugin_schemas import (
    AuthorInfo,
    MarketplaceManifest,
    MarketplaceMetadata,
    OwnerInfo,
    PluginEntry,
    PluginManifest,
)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _load_template(name: str) -> Template:
    return Template((_TEMPLATES_DIR / name).read_text(encoding="utf-8"))


_SKILL_TMPL = _load_template("skill.md.tmpl")
_README_TMPL = _load_template("readme.md.tmpl")
_HOOK_TMPL = _load_template("verify_hook.sh.tmpl")

# Per-language install hints surfaced when the SessionStart hook fails.
# Languages without an entry get the generic "see plugin README" pointer.
_INSTALL_HINTS: dict[str, str] = {
    "rust": "rustup component add rust-analyzer",
    "python": "pipx install python-lsp-server",
    "typescript": "npm i -g typescript-language-server typescript",
    "go": "go install golang.org/x/tools/gopls@latest",
}

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


class _FacadeLike(Protocol):
    """Structural subset of a facade entry the skill renderer depends on."""

    name: str
    summary: str
    trigger_phrases: tuple[str, ...]
    primitive_chain: tuple[str, ...]


class _StrategyWithFacades(_StrategyLike, Protocol):
    """``_StrategyLike`` plus the facade tuple consumed by README + emit."""

    facades: tuple[_FacadeLike, ...]


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


def _render_mcp_json(strategy: _StrategyLike) -> str:
    """Render the ``.mcp.json`` registering one MCP server per language."""

    payload = {
        "mcpServers": {
            f"scalpel-{strategy.language}": {
                "command": "uvx",
                "args": [
                    "--from",
                    "git+https://github.com/o2services/o2-scalpel.git#subdirectory=vendor/serena",
                    "serena-mcp",
                    "--language",
                    strategy.language,
                ],
                "env": {},
            }
        }
    }
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _render_marketplace_json(strategies: list[_StrategyLike]) -> str:
    """Render the top-level ``marketplace.json`` aggregator.

    Plugin entries are sorted by ``language`` so the output is byte-identical
    regardless of input order — caller can pass strategies in any sequence.
    """

    sorted_strats = sorted(strategies, key=lambda s: s.language)
    entries = [
        PluginEntry(
            name=_plugin_name(s),
            source=f"./{_plugin_name(s)}",
            description=_description(s),
        )
        for s in sorted_strats
    ]
    manifest = MarketplaceManifest(
        name="o2-scalpel",
        metadata=MarketplaceMetadata(),
        owner=OwnerInfo(name=_AUTHOR),
        plugins=entries,
    )
    payload = manifest.model_dump(mode="json", by_alias=True)
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _skill_name_for(strategy: _StrategyLike, facade: _FacadeLike) -> str:
    """Compute the canonical skill name for a (strategy, facade) pair."""

    return f"using-scalpel-{facade.name.replace('_', '-')}-{strategy.language}"


def _render_skill_for_facade(
    strategy: _StrategyLike, facade: _FacadeLike
) -> str:
    """Render a single ``skills/using-scalpel-<facade>-<lang>.md`` file."""

    skill_name = _skill_name_for(strategy, facade)
    description = (
        f"When user asks to {facade.summary.lower()} in {strategy.display_name}, "
        f"use scalpel_{facade.name}"
    )
    trigger_list = "\n".join(f'- "{p}"' for p in facade.trigger_phrases)
    primitive_list = "\n".join(
        f"{i + 1}. `{p}`" for i, p in enumerate(facade.primitive_chain)
    )
    return _SKILL_TMPL.substitute(
        skill_name=skill_name,
        description=description,
        title=f"Scalpel - {facade.name} ({strategy.display_name})",
        summary=facade.summary,
        facade=facade.name,
        language=strategy.language,
        trigger_list=trigger_list,
        primitive_list=primitive_list,
    )


def _render_readme(strategy: _StrategyWithFacades) -> str:
    """Render the per-plugin ``README.md``."""

    rows = ["| Facade | Summary |", "|---|---|"]
    for facade in strategy.facades:
        rows.append(f"| `scalpel_{facade.name}` | {facade.summary} |")
    table = "\n".join(rows)
    return _README_TMPL.substitute(
        plugin_name=_plugin_name(strategy),
        description=_description(strategy),
        lsp_cmd=strategy.lsp_server_cmd[0],
        extensions=", ".join(strategy.file_extensions),
        facade_table=table,
    )


def _render_session_start_hook(strategy: _StrategyLike) -> str:
    """Render the POSIX-sh ``hooks/verify-scalpel-<lang>.sh`` probe."""

    return _HOOK_TMPL.substitute(
        plugin_name=_plugin_name(strategy),
        lsp_cmd=strategy.lsp_server_cmd[0],
        install_hint=_INSTALL_HINTS.get(strategy.language, "see plugin README"),
        language=strategy.language,
    )


__all__ = [
    "PluginManifest",  # re-export for callers
    "_render_marketplace_json",
    "_render_mcp_json",
    "_render_plugin_json",
    "_render_readme",
    "_render_session_start_hook",
    "_render_skill_for_facade",
]
