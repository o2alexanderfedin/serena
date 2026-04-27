"""Lazy-import-trap fixture. The test passes if a.compute() and b.echo()
both work despite a->b and b->a circular references; it fails if either
import has been promoted from function-body scope to module-top-level."""
from __future__ import annotations
import importlib
import sys


def test_a_calls_b_lazily() -> None:
    a = importlib.import_module("calcpy_circular.a")
    assert a.compute(7) == 14  # a.compute calls b.double internally


def test_b_calls_a_lazily() -> None:
    b = importlib.import_module("calcpy_circular.b")
    assert b.echo("hi") == "echo:hi"


def test_no_top_level_cross_import() -> None:
    """If a refactor promoted the lazy import, this would ImportError on first import."""
    for mod in ("calcpy_circular", "calcpy_circular.a", "calcpy_circular.b"):
        sys.modules.pop(mod, None)
    importlib.import_module("calcpy_circular.a")  # must not raise
    importlib.import_module("calcpy_circular.b")  # must not raise
