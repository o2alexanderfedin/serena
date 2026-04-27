"""Canonical record of the P5a pylsp-mypy SHIP decision.

Source: P5a.md:5-14. Reconciles WHAT-REMAINS.md §1 reversal:
stale_rate 8.33% -> 0.00%, p95 8.011s -> 2.668s.
``axes_that_failed_falsifier_check`` = axes where the falsifier threshold
(>=5% stale, >=3s p95) was NOT crossed on re-run, i.e., axes that
"passed" by failing to falsify, satisfying outcome B per P5a.md:30.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class P5aMypyDecision(BaseModel):
    """Frozen pydantic record encoding the ratified pylsp-mypy outcome."""

    model_config = ConfigDict(frozen=True)

    outcome: Literal["SHIP", "DROP"]
    stale_rate: float
    p95_latency_seconds: float
    axes_that_failed_falsifier_check: tuple[str, ...]
    pylsp_initialization_options: dict[str, Any]


P5A_MYPY_DECISION = P5aMypyDecision(
    outcome="SHIP",
    stale_rate=0.0,
    p95_latency_seconds=2.668,
    axes_that_failed_falsifier_check=("stale_rate", "p95_latency"),
    pylsp_initialization_options={
        "pylsp": {
            "plugins": {
                "pylsp_mypy": {
                    "enabled": True,
                    "live_mode": False,
                    "dmypy": True,
                },
            },
        },
    },
)
