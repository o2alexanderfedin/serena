"""Module ``b`` — depends on ``a`` lazily inside ``combine()``.

Mirror of ``a.py``: the lazy import below MUST stay function-scoped.
"""

from __future__ import annotations


def combine(x: int, y: int) -> int:
    """Add via the lazy peer module's ``double`` helper."""
    from calcpy_circular import a
    return a.double(x) + y
