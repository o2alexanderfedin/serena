"""Type stub paralleling calcpy.calcpy public surface.

basedpyright reads this file in preference to inspecting the .py body
for type-inference. The stub mirrors only the public API listed in
``__all__``; private helpers (``_Evaluator``, ``_parse_*``, etc.) are
intentionally omitted.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

__all__: list[str]

DEBUG: bool
_MAX_DEPTH: int


class TokenKind:
    INT: str
    FLOAT: str
    PLUS: str
    MINUS: str
    STAR: str
    SLASH: str
    LPAREN: str
    RPAREN: str
    EOF: str

    class TokenStream:
        def __init__(self, tokens: Sequence[Token]) -> None: ...
        def peek(self) -> Token: ...
        def advance(self) -> Token: ...
        def at_end(self) -> bool: ...


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    pos: int


class ParseError(Exception): ...


class AstNode: ...


@dataclass(frozen=True)
class IntLit(AstNode):
    value: int


@dataclass(frozen=True)
class FloatLit(AstNode):
    value: float


@dataclass(frozen=True)
class BinOp(AstNode):
    op: str
    left: AstNode
    right: AstNode


@dataclass(frozen=True)
class UnaryOp(AstNode):
    op: str
    operand: AstNode


def tokenize(source: str) -> list[Token]: ...
def parse(source: str) -> AstNode: ...
def evaluate(node: AstNode) -> int | float: ...
