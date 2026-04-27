"""Runs all doctests in calcpy.calcpy. The E10-py gate."""
from __future__ import annotations
import doctest
import calcpy.calcpy


def test_doctests_pass() -> None:
    results = doctest.testmod(calcpy.calcpy, verbose=False)
    assert results.failed == 0, f"{results.failed} doctests failed"
