"""Asserts `from calcpy import *` exposes the same name set across refactors."""
from __future__ import annotations


def test_public_names_stable() -> None:
    import calcpy
    expected = {"AstNode", "BinOp", "FloatLit", "IntLit", "ParseError",
                "Token", "TokenKind", "UnaryOp", "evaluate", "parse", "tokenize"}
    assert set(calcpy.__all__) == expected
    assert all(hasattr(calcpy, n) for n in expected)
