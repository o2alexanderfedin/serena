"""Module b - calls a lazily to avoid circular-import ImportError."""
from __future__ import annotations


def double(n: int) -> int:
    return n * 2


def echo(s: str) -> str:
    """Delegates to a.echo_local (lazy import keeps the ref out of module scope)."""
    from calcpy_circular import a  # NOTE: lazy. DO NOT promote to top-level.

    return f"echo:{a.echo_local(s).split(':', 1)[1]}"
