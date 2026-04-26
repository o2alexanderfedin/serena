"""Sibling-plugin discovery (Stage 1C §14.1 file 9).

Claude Code installs plugins under ``~/.claude/plugins/cache/<owner>__<repo>/<plugin>/``;
each plugin folder carries ``.claude-plugin/plugin.json``. A scalpel companion
plugin declares its language via a ``scalpel.language`` field in that
manifest. This module enumerates those companions so the pool knows which
``LspPoolKey.language`` values are reachable on the user's host.

``O2_SCALPEL_DISABLE_LANGS`` (comma-separated language ids) is honoured by
``enabled_languages``; the pool then refuses to spawn for those keys with
a structured error (Stage 1G ``scalpel_apply_capability`` surfaces it as
``language_disabled_by_user`` per §16.2 row 1/2).

Per §6.10 the distribution path is ``uvx --from <local-path>`` at MVP and
marketplace at v1.1; the discovery walker is the seam that lets a user
install scalpel companions independently and have the pool pick them up
without restart.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

log = logging.getLogger("serena.refactoring.discovery")


def default_cache_root() -> Path:
    """Probe ``~/.claude/plugins/cache`` (canonicalised)."""
    return (Path.home() / ".claude" / "plugins" / "cache").resolve()


class PluginRecord(BaseModel):
    """One discovered scalpel companion plugin."""

    name: str
    version: str | None = None
    language: str
    path: Path

    model_config = {"frozen": True, "arbitrary_types_allowed": True}


@lru_cache(maxsize=8)
def discover_sibling_plugins(cache_root: Path | None = None) -> tuple[PluginRecord, ...]:
    """Walk ``cache_root`` for ``.claude-plugin/plugin.json`` manifests carrying a
    ``scalpel.language`` field.

    Returns a tuple (so the result is hashable & lru_cache-compatible) of
    :class:`PluginRecord`. Plugins missing the ``scalpel`` section, or whose
    manifest is malformed, are silently skipped (logged at WARNING).
    """
    root = (cache_root or default_cache_root()).resolve()
    if not root.exists():
        return ()
    out: list[PluginRecord] = []
    for manifest in root.glob("*/*/.claude-plugin/plugin.json"):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            log.warning("discovery: malformed manifest %s: %s", manifest, e)
            continue
        scalpel = data.get("scalpel")
        if not isinstance(scalpel, dict):
            continue
        language = scalpel.get("language")
        if not isinstance(language, str) or not language:
            log.warning("discovery: %s has scalpel section without 'language'", manifest)
            continue
        plugin_dir = manifest.parent.parent
        try:
            rec = PluginRecord(
                name=str(data.get("name") or plugin_dir.name),
                version=data.get("version"),
                language=language,
                path=plugin_dir.resolve(),
            )
        except Exception as e:  # pragma: no cover — pydantic validation errors
            log.warning("discovery: %s pydantic-rejected: %s", manifest, e)
            continue
        out.append(rec)
    return tuple(out)


def enabled_languages(records: tuple[PluginRecord, ...] | list[PluginRecord]) -> frozenset[str]:
    """Languages reachable after honouring ``O2_SCALPEL_DISABLE_LANGS``.

    The env var is a comma-separated list of language ids to drop. Whitespace
    around ids is trimmed; empty entries ignored.
    """
    raw = os.environ.get("O2_SCALPEL_DISABLE_LANGS", "")
    disabled = frozenset(p.strip() for p in raw.split(",") if p.strip())
    return frozenset(r.language for r in records if r.language not in disabled)
