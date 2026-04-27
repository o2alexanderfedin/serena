"""Stream 5 / Leaf 03 Task 2 — in-process plugin registry.

The registry scans the parent o2-scalpel multi-plugin tree
(``<plugins_dir>/<plugin>/.claude-plugin/plugin.json``) and exposes an
atomic :meth:`PluginRegistry.reload` operation that swaps the in-memory
state on success. Per Q10, refresh is explicit (no filesystem watcher) —
the user (or the LLM via ``scalpel_reload_plugins``) calls it after a
plugin tree changes on disk.

Validation reuses :class:`serena.refactoring.plugin_schemas.PluginManifest`
so the runtime shares one source of truth with the Stage 1J generator.
Plugins that fail validation surface as per-plugin entries in
:class:`ReloadReport.errors` — they DO NOT block reload of healthy
sibling plugins (per the spec self-review checklist).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from serena.plugins.reload_report import ReloadReport
from serena.refactoring.plugin_schemas import PluginManifest


class PluginRegistry:
    """In-process registry of validated plugin manifests.

    Stable identity: a plugin is identified by the ``name`` field of its
    ``plugin.json`` (boostvolt-shape ``[a-z][a-z0-9-]*``). The directory
    name is *not* authoritative — the manifest's ``name`` wins so the
    registry lines up with what Claude Code marketplaces will surface.
    """

    def __init__(self, plugins_dir: Path) -> None:
        """Bind the registry to a directory of plugin trees.

        :param plugins_dir: directory whose immediate subdirectories are
            individual plugin trees (each containing
            ``.claude-plugin/plugin.json``). Empty / missing directories
            are tolerated — :meth:`list_ids` simply returns ``[]`` until
            a manifest appears.
        """
        self._plugins_dir = plugins_dir
        # _state is populated by reload(); construction does NOT scan so
        # callers control when disk I/O happens (matches Stage 1J generator
        # idempotence — repeat constructors are cheap).
        self._state: dict[str, PluginManifest] = {}
        self._errors: tuple[tuple[str, str], ...] = ()

    # --- public API --------------------------------------------------

    def list_ids(self) -> list[str]:
        """Return sorted plugin ids currently held in the registry."""
        return sorted(self._state.keys())

    def get(self, plugin_id: str) -> PluginManifest | None:
        """Return the manifest for ``plugin_id`` or ``None``."""
        return self._state.get(plugin_id)

    def errors(self) -> tuple[tuple[str, str], ...]:
        """Return the per-plugin errors recorded by the most recent reload."""
        return self._errors

    def reload(self) -> ReloadReport:
        """Atomically rescan ``plugins_dir`` and swap in the new state.

        Errors are *per-plugin* and DO NOT block sibling plugins from
        loading — a malformed ``plugin.json`` surfaces as an entry in
        :attr:`ReloadReport.errors` while the healthy plugins continue
        to load. The previous state is replaced on the very last line so
        a crash mid-scan leaves the registry untouched.
        """
        new_state, errors = self._scan(self._plugins_dir)
        old_ids = set(self._state.keys())
        new_ids = set(new_state.keys())
        added = tuple(sorted(new_ids - old_ids))
        removed = tuple(sorted(old_ids - new_ids))
        unchanged = tuple(sorted(old_ids & new_ids))
        # Atomic swap — keep the in-memory state untouched until both
        # the scan and error tuple are fully assembled.
        self._state = new_state
        self._errors = errors
        return ReloadReport(
            added=added,
            removed=removed,
            unchanged=unchanged,
            errors=errors,
        )

    # --- internal ----------------------------------------------------

    @staticmethod
    def _scan(
        plugins_dir: Path,
    ) -> tuple[dict[str, PluginManifest], tuple[tuple[str, str], ...]]:
        """Walk ``plugins_dir`` and build the new state + error list.

        Each immediate subdirectory is treated as a candidate plugin.
        A subdirectory without ``.claude-plugin/plugin.json`` is skipped
        silently (it might be a hand-managed sibling). A subdirectory
        whose ``plugin.json`` exists but fails to parse / validate
        surfaces as an error keyed by the directory name.
        """
        new_state: dict[str, PluginManifest] = {}
        errors: list[tuple[str, str]] = []
        if not plugins_dir.exists() or not plugins_dir.is_dir():
            return new_state, ()
        for child in sorted(plugins_dir.iterdir()):
            if not child.is_dir():
                continue
            manifest_path = child / ".claude-plugin" / "plugin.json"
            if not manifest_path.is_file():
                continue
            raw: Any
            try:
                raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append((child.name, f"failed to read plugin.json: {exc}"))
                continue
            if not isinstance(raw, dict):
                errors.append((
                    child.name,
                    f"plugin.json must be a JSON object, got {type(raw).__name__}",
                ))
                continue
            # Strip generator metadata (private ``_*`` keys) before
            # validation — PluginManifest forbids extras and the
            # generator stamps a ``_generator`` provenance field.
            cleaned = {k: v for k, v in raw.items() if not k.startswith("_")}
            try:
                manifest = PluginManifest.model_validate(cleaned)
            except ValidationError as exc:
                errors.append((child.name, f"validation failed: {exc.errors()[0]['msg']}"))
                continue
            # Manifest ``name`` is authoritative — duplicate names from
            # two sibling directories surface as an error rather than
            # silently overwriting.
            if manifest.name in new_state:
                errors.append((
                    manifest.name,
                    f"duplicate plugin name; second occurrence at {child}",
                ))
                continue
            new_state[manifest.name] = manifest
        return new_state, tuple(errors)


__all__ = ["PluginRegistry"]
