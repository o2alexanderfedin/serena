"""Kitchen-sink baseline for Stage 2B E2E scenarios.

The four future modules — ast, errors, parser, evaluator — are co-located
here so the E1-py 4-way split scenario can move each cluster into a sibling
file (`calcpy/ast.py`, `calcpy/errors.py`, etc.) and the post-split
``pytest -q`` continues to pass byte-identically against the baseline below.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union


# --- ast cluster ----------------------------------------------------------

@dataclass(frozen=True)
class Num:
    value: int


@dataclass(frozen=True)
class Add:
    left: "Expr"
    right: "Expr"


@dataclass(frozen=True)
class Sub:
    left: "Expr"
    right: "Expr"


@dataclass(frozen=True)
class Mul:
    left: "Expr"
    right: "Expr"


@dataclass(frozen=True)
class Div:
    left: "Expr"
    right: "Expr"


Expr = Union[Num, Add, Sub, Mul, Div]


# --- errors cluster -------------------------------------------------------

class CalcError(Exception):
    """Base class for calcpy errors."""


class ParseError(CalcError):
    pass


class DivisionByZero(CalcError):
    pass


# --- parser cluster -------------------------------------------------------

def parse(text: str) -> Expr:
    s = text.strip()
    for op_char, ctor in (("+", Add), ("-", Sub), ("*", Mul), ("/", Div)):
        idx = s.rfind(op_char)
        if idx > 0:
            return ctor(parse(s[:idx]), parse(s[idx + 1 :]))
    try:
        return Num(int(s))
    except ValueError as e:
        raise ParseError(str(e)) from e


# --- evaluator cluster ----------------------------------------------------

def evaluate(expr: Expr) -> int:
    if isinstance(expr, Num):
        return expr.value
    if isinstance(expr, Add):
        return evaluate(expr.left) + evaluate(expr.right)
    if isinstance(expr, Sub):
        return evaluate(expr.left) - evaluate(expr.right)
    if isinstance(expr, Mul):
        return evaluate(expr.left) * evaluate(expr.right)
    if isinstance(expr, Div):
        r = evaluate(expr.right)
        if r == 0:
            raise DivisionByZero("division by zero")
        return evaluate(expr.left) // r
    raise ParseError(f"unknown expr {expr!r}")
