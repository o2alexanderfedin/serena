"""Module a - calls b lazily to avoid circular-import ImportError."""
from __future__ import annotations


def compute(x: int) -> int:
    """Doubles via b.double (lazy import keeps the ref out of module scope)."""
    from calcpy_circular import b  # NOTE: lazy. DO NOT promote to top-level.

    return b.double(x)


def echo_local(s: str) -> str:
    return f"a:{s}"
