"""Headline ``calcpy`` fixture package — minimum scope per Stage 1H v0.1.0.

The full Stage 1H plan budgets ~1,840 LoC of Python fixture surface
(calcpy.py monolith + .pyi stub + 4 sub-fixtures).  v0.1.0 ships only
``calcpy/core.py`` so the integration harness has at least one Python
package that pylsp/basedpyright/ruff can advertise code actions on.
The deferred surface is routed to v0.2.0.  See
``docs/superpowers/plans/stage-1h-results/PROGRESS.md``.
"""
from __future__ import annotations

from .core import (
    AstNode,
    Calculator,
    ParseError,
    evaluate,
    parse,
    tokenize,
)

__all__ = [
    "AstNode",
    "Calculator",
    "ParseError",
    "evaluate",
    "parse",
    "tokenize",
]
