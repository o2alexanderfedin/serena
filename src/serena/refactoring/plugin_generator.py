"""Stage 1J plugin generator — emits ``o2-scalpel-<lang>/`` Claude Code plugin trees.

The generator composes five small ``_render_*`` helpers, each backed by a
pydantic v2 schema and (where applicable) a ``string.Template`` source under
``./templates/``, into a deterministic byte-identical filesystem write rooted
at ``out_parent / o2-scalpel-<language>/``.

Public surface:

* :class:`PluginGenerator` — composition root.
* ``_render_plugin_json(strategy)``
* ``_render_mcp_json(strategy)``
* ``_render_skill_for_facade(strategy, facade)``
* ``_render_readme(strategy)``
* ``_render_session_start_hook(strategy)``

The top-level ``marketplace.json`` aggregator is rendered by
:mod:`serena.marketplace.build`, which walks the per-plugin ``plugin.json``
files written by this generator. v1.2 reconciliation removed the legacy
``_render_marketplace_json`` helper that had duplicated that role; the
single source of truth is now the marketplace package.

All emitted JSON uses ``sort_keys=True, indent=2, ensure_ascii=False`` and
ends in a trailing newline (POSIX). All shell scripts are POSIX ``sh``.
"""

from __future__ import annotations

import json
import shutil
import stat as _stat
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Protocol

from serena.marketplace.build import resolve_engine_sha
from serena.refactoring.plugin_schemas import (
    AuthorInfo,
    PluginManifest,
)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _load_template(name: str) -> Template:
    return Template((_TEMPLATES_DIR / name).read_text(encoding="utf-8"))


_SKILL_TMPL = _load_template("skill.md.tmpl")
_README_TMPL = _load_template("readme.md.tmpl")
_HOOK_TMPL = _load_template("verify_hook.sh.tmpl")
_DASHBOARD_CMD_TMPL = _load_template("dashboard_command.md.tmpl")
_UPDATE_CMD_TMPL = _load_template("update_command.md.tmpl")
_CHECK_UPDATE_HOOK_TMPL = _load_template("check_update_hook.sh.tmpl")
_STATUSLINE_TMPL = _load_template("scalpel_statusline.sh.tmpl")

# Per-language install hints surfaced when the SessionStart hook fails.
# Languages without an entry get the generic "see plugin README" pointer.
_INSTALL_HINTS: dict[str, str] = {
    "rust": "rustup component add rust-analyzer",
    "python": "pipx install python-lsp-server",
    "markdown": "brew install marksman  # macOS; snap install marksman on Linux",
    "typescript": "npm i -g typescript-language-server typescript",
    "go": "go install golang.org/x/tools/gopls@latest",
    # v1.9.8 newcomers
    "haxe": "npm install -g haxe-language-server  # plus Haxe + nekovm on PATH",
    "erlang": "brew install erlang_ls  # macOS; build from github.com/erlang-ls/erlang_ls otherwise",
    "ocaml": "opam install ocaml-lsp-server  # requires opam + an active switch",
    "powershell": "Install-Module -Name PowerShellEditorServices  # from a pwsh prompt",
    "systemverilog": "brew install verible  # macOS; prebuilt at github.com/chipsalliance/verible/releases",
    "clojure": "brew install clojure-lsp/brew/clojure-lsp-native  # macOS; binary at github.com/clojure-lsp/clojure-lsp/releases",
    "crystal": "brew install crystalline  # macOS; or shards build from github.com/elbywan/crystalline",
    "elixir": "brew install elixir-ls  # macOS; build from github.com/elixir-lsp/elixir-ls otherwise",
    "haskell": "ghcup install hls --set  # installs haskell-language-server via the Haskell toolchain manager",
    "perl": "cpanm Perl::LanguageServer  # requires cpanm + a system Perl",
    "ruby": "gem install --user-install ruby-lsp  # add user gem bindir to PATH",
}

# Identity constants for every emitted plugin. Kept module-private so they
# travel with the generator and are easy to lift to env in Stage 1K if we
# ever want to publish plugins under a different owner.
_AUTHOR_NAME = "Alex Fedin & AI Hive®"
_AUTHOR_EMAIL = "af@O2.services"
_AUTHOR_URL = "https://O2.services"
_LICENSE = "MIT"
_REPO = "https://github.com/o2alexanderfedin/o2-scalpel"
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


# Tag suffix added to every scalpel plugin. Kept module-level so the order is
# trivially auditable. The full per-plugin tag list is built by prefixing
# the language id and lsp-cmd, then concatenating these.
_COMMON_TAGS: tuple[str, ...] = ("lsp", "refactor", "mcp", "scalpel")


def _tags_for(strategy: _StrategyLike) -> tuple[str, ...]:
    """Compose the per-plugin marketplace-UI tag list.

    Tags are ordered by significance: ``[language, lsp_cmd, *_COMMON_TAGS]``
    with the lsp_cmd dropped if it is identical to the language id (e.g. the
    Python plugin's ``pylsp`` would still appear since ``pylsp != python``;
    only matches like a hypothetical ``markdown`` lsp_cmd would be elided).
    """

    language = strategy.language
    lsp_cmd = strategy.lsp_server_cmd[0]
    head: tuple[str, ...] = (language,) if lsp_cmd == language else (language, lsp_cmd)
    return head + _COMMON_TAGS


def _render_plugin_json(strategy: _StrategyLike) -> str:
    """Render the boostvolt-shape ``.claude-plugin/plugin.json``."""

    manifest = PluginManifest(
        name=_plugin_name(strategy),
        description=_description(strategy),
        version=_VERSION,
        author=AuthorInfo(name=_AUTHOR_NAME, email=_AUTHOR_EMAIL, url=_AUTHOR_URL),
        license=_LICENSE,
        repository=_REPO,
        homepage=_REPO,
        category="development",
        tags=_tags_for(strategy),
    )
    payload = manifest.model_dump(mode="json", by_alias=True)
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _render_mcp_json(strategy: _StrategyLike) -> str:
    """Render the ``.mcp.json`` registering one MCP server per language.

    Each plugin passes ``--server-name scalpel-<lang>`` as a trailing arg.
    The flag is accepted by ``serena start-mcp-server`` but ignored at runtime;
    its sole purpose is to make every plugin's ``args`` array unique so that
    Claude Code's plugin manager does not deduplicate them when multiple
    o2-scalpel-* plugins are installed simultaneously.
    """

    server_name = f"scalpel-{strategy.language}"
    payload = {
        "mcpServers": {
            server_name: {
                "command": "uvx",
                "args": [
                    "--from",
                    "git+https://github.com/o2alexanderfedin/o2-scalpel-engine.git",
                    "serena",
                    "start-mcp-server",
                    "--server-name",
                    server_name,
                ],
                "env": {},
            }
        }
    }
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
    """Render the per-plugin ``README.md``.

    The rendered document is prefixed with a two-line HTML comment banner
    that carries the current engine SHA, matching the provenance stamp baked
    into ``marketplace.json`` by :func:`serena.marketplace.build._generator_banner`.
    The SHA is resolved via :func:`serena.marketplace.build.resolve_engine_sha`
    so both surfaces stay in sync without caller-side coordination.
    """

    rows = ["| Facade | Summary |", "|---|---|"]
    for facade in strategy.facades:
        rows.append(f"| `scalpel_{facade.name}` | {facade.summary} |")
    table = "\n".join(rows)
    sha = resolve_engine_sha()[:12]
    return _README_TMPL.substitute(
        generator_sha=sha,
        plugin_name=_plugin_name(strategy),
        description=_description(strategy),
        lsp_cmd=strategy.lsp_server_cmd[0],
        extensions=", ".join(strategy.file_extensions),
        facade_table=table,
    )


def _render_dashboard_command(strategy: _StrategyLike) -> str:
    """Render the per-plugin ``commands/o2-scalpel-<lang>-dashboard.md`` slash-command body.

    Each emitted plugin ships a Claude Code slash command that opens the engine
    dashboard for *that plugin's* MCP server (``scalpel-<lang>``). The command
    discovers the actual TCP port at runtime via ``pgrep`` + ``lsof`` — needed
    because (a) the dashboard binds lazily, only after the first tool call,
    and (b) when multiple scalpel-* MCP servers run concurrently, the engine
    increments past 0x5EDA to the first free port.

    The slash command body is identical across plugins except for the two
    template substitutions (``language``, ``plugin_name``); centralising it
    here keeps the 23 emitted ``.md`` files byte-deterministic.
    """
    return _DASHBOARD_CMD_TMPL.substitute(
        language=strategy.language,
        plugin_name=_plugin_name(strategy),
    )


def _render_session_start_hook(strategy: _StrategyLike) -> str:
    """Render the POSIX-sh ``hooks/verify-scalpel-<lang>.sh`` probe."""

    return _HOOK_TMPL.substitute(
        plugin_name=_plugin_name(strategy),
        lsp_cmd=strategy.lsp_server_cmd[0],
        install_hint=_INSTALL_HINTS.get(strategy.language, "see plugin README"),
        language=strategy.language,
    )


def _render_update_command() -> str:
    """Render the per-plugin ``commands/o2-scalpel-update.md`` slash command.

    The body is engine-global (not per-language) — the command refreshes the
    uvx-cached ``o2-scalpel-engine`` and signals running ``scalpel-*`` MCP
    servers to restart. Every plugin emits an identical copy so installing
    any one plugin makes ``/o2-scalpel-update`` available; Claude Code's
    plugin registry deduplicates identical-content slash commands.

    Unlike the other ``_render_*`` helpers this one takes no ``strategy``
    argument because the rendered body is constant across languages — there
    are no $-vars to substitute. ``Template.substitute()`` is still called for
    consistency with the loader contract.
    """
    return _UPDATE_CMD_TMPL.substitute()


def _render_check_update_hook(strategy: _StrategyLike) -> str:
    """Render the per-plugin ``hooks/check-scalpel-update.sh`` SessionStart hook.

    Throttled (1 network call per 6h, shared cache) so when multiple scalpel-*
    plugins are enabled the engine isn't probed N times per session-start.
    """
    return _CHECK_UPDATE_HOOK_TMPL.substitute(
        plugin_name=_plugin_name(strategy),
    )


def _render_statusline_script(strategy: _StrategyLike) -> str:
    """Render the per-plugin ``hooks/scalpel-statusline.sh`` script.

    Shipped per plugin so users can wire ANY plugin's copy as their
    Claude Code ``statusLine.command``. The script reads
    ``~/.cache/o2-scalpel/update-check.json`` and emits a yellow
    ``⬆ /o2-scalpel-update`` segment when an update is available; empty
    otherwise. Cache is written by check-scalpel-update.sh and cleared by
    /o2-scalpel-update.
    """
    return _STATUSLINE_TMPL.substitute(
        plugin_name=_plugin_name(strategy),
    )


def _render_hooks_json(strategy: _StrategyLike) -> str:
    """Render ``hooks/hooks.json`` binding the verify script to SessionStart.

    Without this file Claude Code never discovers or runs the ``verify-scalpel-
    <lang>.sh`` script — failure F4 from install-mechanics §5. The exit code
    in the script must be ``2`` (blocking) for the SessionStart failure to halt
    plugin load rather than silently warn.
    """

    hook_script = f"${{CLAUDE_PLUGIN_ROOT}}/hooks/verify-scalpel-{strategy.language}.sh"
    check_update_script = "${CLAUDE_PLUGIN_ROOT}/hooks/check-scalpel-update.sh"
    payload = {
        "hooks": {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": hook_script,
                        },
                        {
                            "type": "command",
                            "command": check_update_script,
                        },
                    ]
                }
            ]
        }
    }
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


@dataclass(frozen=True)
class PluginGenerator:
    """Composes the six render helpers into a deterministic tree write.

    The class is a frozen dataclass so call-sites can ``PluginGenerator()``
    today and add deterministic configuration knobs (template overrides,
    custom owner, etc.) later without breaking the API.
    """

    def emit(
        self,
        strategy: _StrategyWithFacades,
        out_parent: Path,
        *,
        force: bool = False,
    ) -> Path:
        """Write the full ``out_parent / o2-scalpel-<lang>/`` tree.

        :param strategy: language strategy (must include ``facades``).
        :param out_parent: directory under which the plugin tree is rooted.
        :param force: when ``True``, replace any existing tree at the target
            path; when ``False`` (default) raise :class:`FileExistsError`.
        :return: the path to the newly-written plugin root.
        """

        root = Path(out_parent) / _plugin_name(strategy)
        if root.exists():
            if not force:
                raise FileExistsError(
                    f"Refusing to overwrite {root}; pass force=True"
                )
            shutil.rmtree(root)

        (root / ".claude-plugin").mkdir(parents=True, exist_ok=False)
        (root / "commands").mkdir()
        (root / "hooks").mkdir()
        (root / "skills").mkdir()

        (root / ".claude-plugin" / "plugin.json").write_text(
            _render_plugin_json(strategy), encoding="utf-8"
        )
        (root / ".mcp.json").write_text(
            _render_mcp_json(strategy), encoding="utf-8"
        )
        (root / "README.md").write_text(
            _render_readme(strategy), encoding="utf-8"
        )

        hook_path = root / "hooks" / f"verify-scalpel-{strategy.language}.sh"
        hook_path.write_text(
            _render_session_start_hook(strategy), encoding="utf-8"
        )
        hook_path.chmod(
            hook_path.stat().st_mode
            | _stat.S_IXUSR
            | _stat.S_IXGRP
            | _stat.S_IXOTH
        )
        (root / "hooks" / "hooks.json").write_text(
            _render_hooks_json(strategy), encoding="utf-8"
        )

        cmd_path = (
            root / "commands" / f"{_plugin_name(strategy)}-dashboard.md"
        )
        cmd_path.write_text(
            _render_dashboard_command(strategy), encoding="utf-8"
        )

        # /o2-scalpel-update is engine-global (no language suffix).
        # Every plugin ships an identical copy; Claude Code's plugin registry
        # surfaces a single /o2-scalpel-update so the user has one stable name.
        update_cmd_path = root / "commands" / "o2-scalpel-update.md"
        update_cmd_path.write_text(
            _render_update_command(), encoding="utf-8"
        )

        check_update_path = root / "hooks" / "check-scalpel-update.sh"
        check_update_path.write_text(
            _render_check_update_hook(strategy), encoding="utf-8"
        )
        check_update_path.chmod(
            check_update_path.stat().st_mode
            | _stat.S_IXUSR
            | _stat.S_IXGRP
            | _stat.S_IXOTH
        )

        statusline_path = root / "hooks" / "scalpel-statusline.sh"
        statusline_path.write_text(
            _render_statusline_script(strategy), encoding="utf-8"
        )
        statusline_path.chmod(
            statusline_path.stat().st_mode
            | _stat.S_IXUSR
            | _stat.S_IXGRP
            | _stat.S_IXOTH
        )

        for facade in strategy.facades:
            skill_path = root / "skills" / f"{_skill_name_for(strategy, facade)}.md"
            skill_path.write_text(
                _render_skill_for_facade(strategy, facade), encoding="utf-8"
            )

        return root


__all__ = [
    "PluginGenerator",
    "PluginManifest",  # re-export for callers
    "_render_check_update_hook",
    "_render_dashboard_command",
    "_render_hooks_json",
    "_render_mcp_json",
    "_render_plugin_json",
    "_render_readme",
    "_render_session_start_hook",
    "_render_skill_for_facade",
    "_render_statusline_script",
    "_render_update_command",
]
