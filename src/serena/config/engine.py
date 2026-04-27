"""v1.1 Stream 5 / Leaf 05 — Engine config knob.

Runtime knob for selecting the LSP-write engine implementation. Default
is the bundled ``serena-fork`` (today: o2-scalpel-engine fork of
Serena). Future: alternates such as native LSP-write integrations or
the ``lspee`` multiplexer once 1.0 lands.

Switching engines is a server-restart action (not hot-swap) — keeps
the seam minimal.

Per critic R1: ``engine`` is a registry-validated ``str`` rather than
a single-member ``Literal``. This keeps the seam open for the named
v1.x alternates (``native``, ``lspee``) — adding one becomes a single
``EngineRegistry.default().register(...)`` call with NO Settings
code change.
"""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime knob for selecting the LSP-write engine implementation.

    Reads ``O2_SCALPEL_ENGINE`` from the environment (env_prefix
    ``O2_SCALPEL_`` + field name ``engine``). Validates against the
    process-wide ``EngineRegistry`` so unknown ids fail fast at
    Settings construction time rather than at bootstrap.
    """

    model_config = SettingsConfigDict(env_prefix="O2_SCALPEL_", extra="ignore")
    engine: str = "serena-fork"

    @field_validator("engine")
    @classmethod
    def _validate_engine_is_registered(cls, value: str) -> str:
        # Lazy import (S5): importing the registry at module top would
        # risk a settings-load loop with the bundled-engine applier —
        # the registry's ``default()`` factory references
        # :func:`serena.tools.scalpel_facades._apply_workspace_edit_to_disk`
        # (the production WorkspaceEdit applier), which transitively
        # imports a great deal of the runtime that itself reads
        # Settings. Importing at module top would deadlock the import
        # graph; doing it inside the validator keeps the seam safe.
        from serena.engine.registry import EngineRegistry

        known = set(EngineRegistry.default().keys())
        if value not in known:
            raise ValueError(
                f"engine '{value}' is not registered; "
                f"known engines: {sorted(known)}"
            )
        return value


__all__ = ["Settings"]
