# pyright: reportCallIssue=false, reportGeneralTypeIssues=false, reportRedeclaration=false, reportAssignmentType=false
"""Minimal seed package used by Phase 0 spikes."""
from typing import Final

VERSION: Final = "0.0.0"


def add(a: int, b: int) -> int:
    return a + b


def mul(a: int, b: int) -> int:
    return a * b


def _private_helper(x: int) -> int:
    return -x


__all__ = ["VERSION", "add", "mul"]
BAD_VAR_3: int = None
