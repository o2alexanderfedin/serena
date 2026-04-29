"""v1.5 P3 — drift-CI enforcement of the PREFERRED:/FALLBACK: docstring
convention introduced in spec § 5.

Spec source:
    docs/superpowers/specs/2026-04-29-lsp-feature-coverage-spec.md § 5.2

Convention (spec § 5.2.1):

  * Every ``Scalpel*Tool`` class registered under ``serena.tools`` MUST open
    its docstring with the literal token ``PREFERRED:`` followed by a
    routing-intent summary — except ``ScalpelApplyCapabilityTool``, which
    MUST open with ``FALLBACK:`` so the long-tail dispatcher's role is
    machine-checkable and asymmetric to the named facades.

  * Serena upstream tools defined in ``serena.tools.symbol_tools`` (the
    ``rename_symbol``/``replace_symbol_body``/``insert_*_symbol``/
    ``safe_delete_symbol`` family) MUST NOT start with either token.  Their
    absence of an opener is itself the routing signal: Serena = AST-level
    fallback; Scalpel = LSP-preferred.

A contributor who forgets the opener fails this test — the v1.5 contract.
"""

from __future__ import annotations

import inspect
import re

from serena.tools import ToolRegistry
from serena.tools.symbol_tools import (
    InsertAfterSymbolTool,
    InsertBeforeSymbolTool,
    RenameSymbolTool,
    ReplaceSymbolBodyTool,
    SafeDeleteSymbol,
)

# Spec § 5.2.2: regex anchors on optional whitespace + literal opener +
# whitespace + non-empty prose.  Triple-quote leading whitespace is
# normalised away by ``inspect.cleandoc``.
_PREFERRED_RE = re.compile(r"^\s*PREFERRED:\s+\S")
_FALLBACK_RE = re.compile(r"^\s*FALLBACK:\s+\S")

# Spec § 5.2.1: the dispatcher is the single asymmetric exception.
_FALLBACK_TOOL_NAME = "ScalpelApplyCapabilityTool"


def _scalpel_tool_classes() -> list[type]:
    """All registered tool classes whose Python class name starts with
    ``Scalpel``.

    Mirrors the discovery the dispatcher / catalog do — pulled from the
    live ``ToolRegistry`` rather than via direct imports so a future
    ``Scalpel*Tool`` is auto-included.
    """
    registry = ToolRegistry()
    return [
        cls
        for cls in registry.get_all_tool_classes()
        if cls.__name__.startswith("Scalpel")
    ]


def _docstring_first_line(cls: type) -> str:
    """Return the cleaned-up docstring (or empty string) for matching."""
    raw = inspect.getdoc(cls) or ""
    # ``inspect.getdoc`` already strips uniform leading whitespace and
    # collapses the triple-quote blank line — perfect for the regex match.
    return raw


# ---------------------------------------------------------------------------
# 1. Every Scalpel*Tool except the dispatcher opens with ``PREFERRED:``.
# 2. The dispatcher opens with ``FALLBACK:``.
# ---------------------------------------------------------------------------


def test_scalpel_tools_open_with_preferred_or_fallback() -> None:
    classes = _scalpel_tool_classes()
    assert classes, (
        "ToolRegistry returned zero Scalpel*Tool classes — the discovery "
        "predicate or import wiring is broken."
    )

    failures: list[str] = []
    dispatcher_present = False

    for cls in classes:
        doc = _docstring_first_line(cls)
        if cls.__name__ == _FALLBACK_TOOL_NAME:
            dispatcher_present = True
            if not _FALLBACK_RE.match(doc):
                failures.append(
                    f"{cls.__name__}: expected docstring to open with "
                    f"'FALLBACK: ' (spec § 5.2.1 / § 5.3); got: {doc!r}"
                )
        else:
            if not _PREFERRED_RE.match(doc):
                failures.append(
                    f"{cls.__name__}: expected docstring to open with "
                    f"'PREFERRED: ' (spec § 5.2.1); got: {doc!r}"
                )

    assert not failures, "PREFERRED:/FALLBACK: convention violations:\n" + "\n".join(failures)
    assert dispatcher_present, (
        f"{_FALLBACK_TOOL_NAME} was not discovered by ToolRegistry — "
        "the FALLBACK: asymmetry cannot be enforced."
    )


# ---------------------------------------------------------------------------
# 3. Serena upstream tools must NOT open with either token (preserves the
#    asymmetry that lets the LLM route AST-fallback vs LSP-preferred).
# ---------------------------------------------------------------------------


def test_serena_upstream_tools_do_not_use_routing_openers() -> None:
    upstream = (
        RenameSymbolTool,
        ReplaceSymbolBodyTool,
        InsertAfterSymbolTool,
        InsertBeforeSymbolTool,
        SafeDeleteSymbol,
    )
    for cls in upstream:
        doc = _docstring_first_line(cls)
        assert not _PREFERRED_RE.match(doc), (
            f"{cls.__name__} (Serena upstream) must NOT open with "
            f"'PREFERRED: ' — the absence is the routing signal "
            f"(spec § 5.2.1).  Got: {doc!r}"
        )
        assert not _FALLBACK_RE.match(doc), (
            f"{cls.__name__} (Serena upstream) must NOT open with "
            f"'FALLBACK: ' — that token is reserved for "
            f"ScalpelApplyCapabilityTool (spec § 5.2.1).  Got: {doc!r}"
        )
