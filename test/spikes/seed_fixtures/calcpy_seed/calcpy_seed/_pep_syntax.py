# pyright: reportCallIssue=false, reportGeneralTypeIssues=false, reportRedeclaration=false, reportAssignmentType=false, reportReturnType=false, reportInvalidTypeForm=false
"""Trips Rope on PEP 695 / 701 / 654 if Rope's parser is stale.

This file is NOT imported from `calcpy_seed/__init__.py` because it requires
Python 3.12+ to parse. The P3 spike opens it directly via pylsp `didOpen` and
inspects pylsp's syntax-error diagnostics + pylsp-rope's refactor responses.
"""
from __future__ import annotations


type IntList = list[int]


def fmt_pep701(name: str) -> str:
    return f"hello {f"{name}"}"


def parse_groups(items: list[int]) -> int:
    try:
        return sum(items)
    except* (TypeError, ValueError) as eg:
        return -1  # pyright: ignore  # noqa
