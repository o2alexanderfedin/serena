"""v1.1 Stream 5 / Leaf 05 — engine selection seam.

The ``EngineRegistry`` owns the id → factory mapping for LSP-write
engine implementations. ``Settings.engine`` (in :mod:`serena.config.engine`)
validates against this registry so unknown ids fail fast at construction
time. Adding a new engine is one ``register(...)`` call — see registry
docstring for the critic R1 rationale.
"""

from __future__ import annotations

from serena.engine.registry import EngineProtocol, EngineRegistry

__all__ = ["EngineProtocol", "EngineRegistry"]
