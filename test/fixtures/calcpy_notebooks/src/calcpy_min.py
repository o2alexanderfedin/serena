"""calcpy_min - tiny calculator module with deliberately ugly imports.

The import block is intentionally out-of-canonical-order so ruff's
``source.organizeImports`` has work to do; ``os`` and ``Optional`` are
unused so ``F401`` fires. The companion notebook
``../notebooks/explore.ipynb`` imports :func:`add` from this module.
"""
from __future__ import annotations

# Deliberately ugly: typing import before stdlib, plus an unused stdlib
# import (os) and unused symbol (Optional) so ruff F401 fires and
# source.organizeImports has something to reorder. Pyright is silenced
# per-line because the static "unused" finding is the fixture's purpose,
# not a defect — ruff F401 must still fire for the integration test.
from typing import Optional  # pyright: ignore[reportUnusedImport]

import math
import os  # pyright: ignore[reportUnusedImport]


PI = math.pi


def add(a: int, b: int) -> int:
    """Return ``a + b``."""
    return a + b


def sub(a: int, b: int) -> int:
    """Return ``a - b``."""
    return a - b


def mul(a: int, b: int) -> int:
    """Return ``a * b``."""
    return a * b


def div(a: int, b: int) -> float:
    """Return ``a / b``. Raises ``ZeroDivisionError`` if ``b == 0``."""
    if b == 0:
        raise ZeroDivisionError("calcpy_min.div: divisor must be non-zero")
    return a / b


def circle_area(radius: float) -> float:
    """Return the area of a circle with the given radius."""
    return PI * radius * radius


__all__ = ["PI", "add", "circle_area", "div", "mul", "sub"]
