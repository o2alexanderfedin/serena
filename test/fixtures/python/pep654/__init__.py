"""PEP 654 grammar exemplar — exception groups and ``except*``.

Wraps the canonical ``try`` / ``except*`` pattern (Python ≥ 3.11) so
the Stream 5 Leaf 07 Python facades prove their parsers tolerate
exception-group syntax. PEP 654 is intentionally NOT paired with
``convert_from_relative_imports`` — exception-group semantics
are orthogonal to import paths and this fixture has no relative
imports to convert.

Author: AI Hive(R)
"""
from __future__ import annotations

from collections.abc import Callable


def safe_run(work: Callable[[], None]) -> None:
    try:
        work()
    except* ValueError as eg:
        raise ExceptionGroup("validation", list(eg.exceptions))
    except* (KeyError, IndexError) as eg:
        raise ExceptionGroup("lookup", list(eg.exceptions))


def caller() -> None:
    return safe_run(lambda: None)
