"""Five dataclasses; one already extracted to sub/extracted.py.
The inline-flow integration test (leaf 04 T19) asserts repr equality
pre/post inlining one of the four root dataclasses into a synthetic call site."""
from __future__ import annotations

from calcpy_dataclasses import models
from calcpy_dataclasses.sub import extracted


def test_root_dataclasses_count() -> None:
    import dataclasses
    import inspect

    # Filter to *class objects* — `is_dataclass` returns True for instances
    # too, and ``models.DEFAULT_BOX`` is a module-level Box instance.
    cls_list = [
        c
        for c in vars(models).values()
        if inspect.isclass(c) and dataclasses.is_dataclass(c)
    ]
    assert len(cls_list) == 4


def test_extracted_dataclass_present() -> None:
    import dataclasses

    assert dataclasses.is_dataclass(extracted.Money)


def test_repr_contract() -> None:
    p = models.Point(1, 2)
    assert repr(p) == "Point(x=1, y=2)"
    m = extracted.Money(amount=10, currency="USD")
    assert repr(m) == "Money(amount=10, currency='USD')"
