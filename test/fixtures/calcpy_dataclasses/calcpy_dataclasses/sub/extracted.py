"""The fifth @dataclass already extracted to a sub-module.

This is the *target shape* the inline-flow integration test compares
against — i.e. ``Money`` is the dataclass the test inlines back into the
call site to assert repr equality.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Money:
    """Currency-tagged amount. ``amount`` non-negative; ``currency`` ISO-4217-ish."""

    amount: int
    currency: str

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError(f"Money.amount must be >= 0, got {self.amount}")
        if len(self.currency) != 3:
            raise ValueError(
                f"Money.currency must be a 3-letter code, got {self.currency!r}"
            )


__all__ = ["Money"]
