"""PEP 701 grammar exemplar — formalized f-string grammar.

Demonstrates nested quotes inside f-strings, multi-line expressions
and comments inside braces (all legal in Python ≥ 3.12). Drives the
Stream 5 Leaf 07 Python facades to confirm parsing remains clean.

Author: AI Hive(R)
"""
from __future__ import annotations


def label(name: str, count: int) -> str:
    return f"name='{name}' count={count!r} note={f"inner-{name}"}"


def multiline(items: list[int]) -> str:
    return f"""sum = {
        sum(items)  # nested expression with comment
    }"""


def fetch(x: int) -> str:
    return label(name=str(x), count=x)
