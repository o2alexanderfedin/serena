"""Module ``a`` — depends on ``b`` lazily inside ``compute()``.

The function-scope ``from calcpy_circular import b`` MUST stay function-
scoped; promoting it to module top would create a circular-import
ImportError at ``python -c 'import calcpy_circular.a'``.
"""

from __future__ import annotations


def compute(x: int) -> int:
    """Compute via the lazy peer module.

    The import below is deliberately function-scoped to break the
    a.py <-> b.py cycle. Do not promote.
    """
    from calcpy_circular import b
    return b.combine(x, 1)


def double(x: int) -> int:
    return x * 2
