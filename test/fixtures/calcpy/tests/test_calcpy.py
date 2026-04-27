"""End-to-end test for the calcpy monolith: parse/evaluate/tokenize.
Pre-monolith, this fails because calcpy.calcpy module is absent."""
from __future__ import annotations
import pytest
from calcpy import evaluate, parse, tokenize, ParseError


def test_evaluate_int_literal() -> None:
    assert evaluate(parse("42")) == 42


def test_evaluate_addition() -> None:
    assert evaluate(parse("1 + 2")) == 3


def test_evaluate_precedence() -> None:
    assert evaluate(parse("1 + 2 * 3")) == 7


def test_evaluate_parens() -> None:
    assert evaluate(parse("(1 + 2) * 3")) == 9


def test_tokenize_basic() -> None:
    toks = tokenize("1 + 2")
    kinds = [t.kind for t in toks]
    assert kinds == ["INT", "PLUS", "INT"]


def test_parse_error_on_garbage() -> None:
    with pytest.raises(ParseError):
        parse("1 + + 2")


def test_evaluate_unary_minus() -> None:
    assert evaluate(parse("-5")) == -5


def test_evaluate_division_by_zero_raises() -> None:
    with pytest.raises(ZeroDivisionError):
        evaluate(parse("1 / 0"))


def test_evaluate_float_literal() -> None:
    assert evaluate(parse("3.14")) == pytest.approx(3.14)


def test_evaluate_nested() -> None:
    assert evaluate(parse("((1 + 2) * (3 + 4)) - 5")) == 16
