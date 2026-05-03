"""PEP 695 grammar exemplar — type-alias statement + generic class syntax.

Exercises modern Python ≥ 3.12 grammar so the Stream 5 Leaf 07 facades
(``convert_to_async`` / ``annotate_return_type`` /
``convert_from_relative_imports``) prove their parsers handle
PEP 695 cleanly.

Author: AI Hive(R)
"""
from __future__ import annotations

type Vec2 = tuple[float, float]


class Box[T]:
    def __init__(self, value: T) -> None:
        self.value = value


def two() -> int:
    return 2


def fetch(b: Box[int]) -> int:
    return b.value
