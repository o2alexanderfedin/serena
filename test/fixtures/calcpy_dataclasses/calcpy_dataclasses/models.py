"""Four root @dataclass declarations + one module-level DEFAULT_BOX constant.

Each dataclass validates non-negative numerics in ``__post_init__``. The
inline-flow integration test (leaf 04 T19) asserts repr equality pre/post
inlining one of these four into a synthetic call site.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Point:
    """Two-dimensional integer point. Non-negative coordinates."""

    x: int
    y: int

    def __post_init__(self) -> None:
        if self.x < 0:
            raise ValueError(f"Point.x must be >= 0, got {self.x}")
        if self.y < 0:
            raise ValueError(f"Point.y must be >= 0, got {self.y}")


@dataclass
class User:
    """Application user record. ``id`` is non-negative; ``email`` non-empty."""

    id: int
    name: str
    email: str

    def __post_init__(self) -> None:
        if self.id < 0:
            raise ValueError(f"User.id must be >= 0, got {self.id}")
        if not self.email:
            raise ValueError("User.email must be non-empty")


@dataclass
class Order:
    """Customer order. ``total`` is in minor units (cents); non-negative."""

    id: int
    total: int
    items: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.id < 0:
            raise ValueError(f"Order.id must be >= 0, got {self.id}")
        if self.total < 0:
            raise ValueError(f"Order.total must be >= 0, got {self.total}")


@dataclass
class Box:
    """3-D box. All dimensions non-negative."""

    width: int
    height: int
    depth: int

    def __post_init__(self) -> None:
        for label, dim in (
            ("width", self.width),
            ("height", self.height),
            ("depth", self.depth),
        ):
            if dim < 0:
                raise ValueError(f"Box.{label} must be >= 0, got {dim}")


# Module-level constant exercised by the inline-flow integration test;
# inlining must preserve this DEFAULT_BOX reference verbatim.
DEFAULT_BOX: Box = Box(width=1, height=1, depth=1)


__all__ = ["Box", "DEFAULT_BOX", "Order", "Point", "User"]
