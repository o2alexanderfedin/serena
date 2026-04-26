"""Minimal calcpy core — refactor target for the Stage 1H smoke harness.

This module deliberately contains a few "ugly-on-purpose" features so
ruff and pylsp-rope can offer code actions against it:

* an unsorted, partially-unused import block (drives
  ``source.organizeImports``);
* a function with a local that could be extracted (drives
  ``refactor.extract.variable``);
* a class with a method that could be inlined (drives
  ``refactor.inline``);
* a top-level `__all__` re-export so downstream tests can assert public
  API stability.

The full headline calcpy module (~950 LoC across 10 ugly-on-purpose
patterns per specialist-python.md §11.2) lands in v0.2.0; this is the
minimum surface needed for the Stage 1H smoke gate.
"""
from __future__ import annotations

import math  # noqa: F401 — present for ``source.organizeImports`` drift target.
import os
import sys  # noqa: F401 — present for ``source.organizeImports`` drift target.
from dataclasses import dataclass
from typing import Final, Iterable

DEFAULT_PRECISION: Final[int] = 6


class ParseError(ValueError):
    """Raised when ``parse`` encounters invalid input."""


@dataclass(frozen=True)
class AstNode:
    """A literal arithmetic expression node."""

    op: str
    value: float | None = None
    children: tuple["AstNode", ...] = ()

    def is_literal(self) -> bool:
        return self.op == "lit"


def tokenize(source: str) -> list[str]:
    """Split ``source`` into whitespace-separated tokens."""
    if not isinstance(source, str):
        raise ParseError(f"expected str, got {type(source).__name__}")
    return [t for t in source.split() if t]


def parse(source: str) -> AstNode:
    """Parse a tiny RPN expression.  Returns a literal-only AST today."""
    tokens = tokenize(source)
    if not tokens:
        raise ParseError("empty expression")
    head = tokens[0]
    try:
        value = float(head)
    except ValueError as exc:
        raise ParseError(f"not a number: {head!r}") from exc
    return AstNode(op="lit", value=value)


def evaluate(node: AstNode) -> float:
    """Evaluate an ``AstNode``.  Only literal nodes are supported in v0.1.0."""
    if node.is_literal() and node.value is not None:
        return float(node.value)
    raise ParseError(f"unsupported op: {node.op!r}")


class Calculator:
    """Tiny stateful calculator used by smoke-test fixtures."""

    def __init__(self, history: Iterable[float] | None = None) -> None:
        self._history: list[float] = list(history) if history is not None else []

    @property
    def history(self) -> tuple[float, ...]:
        return tuple(self._history)

    def push(self, value: float) -> None:
        self._history.append(value)

    def evaluate_source(self, source: str) -> float:
        result = evaluate(parse(source))
        self.push(result)
        return result

    def reset(self) -> None:
        self._history.clear()


def precision_from_env(default: int = DEFAULT_PRECISION) -> int:
    """Read ``CALCPY_PRECISION`` env var, falling back to ``default``."""
    raw = os.environ.get("CALCPY_PRECISION")
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


__all__ = [
    "AstNode",
    "Calculator",
    "DEFAULT_PRECISION",
    "ParseError",
    "evaluate",
    "parse",
    "precision_from_env",
    "tokenize",
]
