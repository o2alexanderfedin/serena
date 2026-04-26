import pytest

from calcpy import DivisionByZero, evaluate, parse


def test_add_two_plus_three():
    assert evaluate(parse("2+3")) == 5


def test_mul_four_times_five():
    assert evaluate(parse("4*5")) == 20


def test_div_hundred_by_four():
    assert evaluate(parse("100/4")) == 25


def test_div_by_zero_raises():
    with pytest.raises(DivisionByZero):
        evaluate(parse("1/0"))
