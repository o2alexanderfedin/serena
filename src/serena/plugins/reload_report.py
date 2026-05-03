"""Stream 5 / Leaf 03 Task 1 — ``ReloadReport`` pydantic schema.

Surfaces the diff between the previous and freshly-rescanned plugin trees
returned by :meth:`serena.plugins.registry.PluginRegistry.reload`. The
report is serialised to JSON by ``ReloadPluginsTool.apply`` and
returned across the MCP boundary so the LLM can see exactly what changed
without restarting the server (Q10: explicit-refresh model, no filesystem
watcher).

Frozen + ``extra="forbid"`` so any drift in field names surfaces
immediately rather than landing as a silent regression in the wire payload.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, computed_field


class ReloadReport(BaseModel):
    """Diff between previous and rescanned plugin trees."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    added: tuple[str, ...]
    """Plugin ids present after reload but absent before. Sorted."""

    removed: tuple[str, ...]
    """Plugin ids present before reload but absent after. Sorted."""

    unchanged: tuple[str, ...]
    """Plugin ids present before and after reload. Sorted."""

    errors: tuple[tuple[str, str], ...]
    """Per-plugin ``(id, message)`` pairs surfaced during reload.

    A non-empty tuple flips :attr:`is_clean` to ``False``. Errors are
    *per-plugin*, so a healthy plugin still loads even when a sibling
    plugin's manifest is malformed.
    """

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_clean(self) -> bool:
        """``True`` iff no per-plugin errors were surfaced."""
        return not self.errors


__all__ = ["ReloadReport"]
