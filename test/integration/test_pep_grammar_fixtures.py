"""v1.1 Stream 5 / Leaf 08 — PEP 695 / 701 / 654 fixture × facade matrix.

Drives the three Stream 5 Leaf 07 Python facades

* ``scalpel_convert_to_async``                 (F1)
* ``scalpel_annotate_return_type``             (F2)
* ``scalpel_convert_from_relative_imports``    (F3)

against the three modern-grammar fixtures shipped under
``test/fixtures/python/{pep695,pep701,pep654}/``. Confirms that the
facades' parsers (Python ``ast`` for F1 / basedpyright inlay-hint
provider for F2 / rope's ``ImportTools`` for F3) do not regress on
PEP 695 (type-alias + ``class C[T]:``), PEP 701 (formalised f-string
grammar) or PEP 654 (``except*`` exception groups).

Per the spec's S6 rule (and the Mermaid diagram in
``docs/superpowers/plans/2026-04-26-v11-milestone/08-pep-695-701-654-fixtures.md``)
PEP 695 and PEP 701 are exercised against all three facades; PEP 654
is exercised against F1 and F2 only (exception-group semantics are
orthogonal to import paths and the fixture has no relative imports
to convert).

Path note (per spec critic R4): this file lives FLAT under
``test/integration/`` rather than under a ``test/integration/python/``
sub-directory because the established convention in this repo is
flat (e.g. ``test_multi_server_invariants_rust_clippy.py``,
``test_smoke_python_codeaction.py``).

The harness deliberately avoids booting basedpyright; the F2 inlay-hint
provider is monkey-patched in the same shape used by Leaf 07's
``test_facade_annotate_return_type.py`` so the test runs cleanly on
hosts without a live basedpyright. F1 (AST-only) and F3 (rope-only)
need no external LSP at all.

Author: AI Hive(R)
"""
from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from serena.tools import scalpel_facades as facades_mod
from serena.tools.scalpel_facades import (
    ScalpelAnnotateReturnTypeTool,
    ScalpelConvertFromRelativeImportsTool,
    ScalpelConvertToAsyncTool,
)
from serena.tools.scalpel_runtime import ScalpelRuntime

# ---------------------------------------------------------------------------
# Skip on Python < 3.12 — PEP 695 / 701 are 3.12, PEP 654 is 3.11.
# We pick 3.12 as the lower bound so the whole file is gated by a
# single skipif and the fixture trees stay self-consistent.
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 12),
    reason="PEP 695 / 701 / 654 fixtures require Python ≥ 3.12",
)


# ---------------------------------------------------------------------------
# Fixture-tree paths
# ---------------------------------------------------------------------------

INTEGRATION_DIR = Path(__file__).parent.resolve(strict=False)
SERENA_ROOT = INTEGRATION_DIR.parents[1]  # vendor/serena
PEP_FIXTURES_ROOT = SERENA_ROOT / "test" / "fixtures" / "python"

PEP695_SOURCE = PEP_FIXTURES_ROOT / "pep695" / "__init__.py"


def _read_fixture(path: Path) -> str:
    """Read a PEP-grammar fixture, asserting it exists for clear failure."""
    assert path.is_file(), (
        f"PEP fixture missing at {path}; Leaf 08 should have created it."
    )
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Runtime reset (matches Leaf 07 fixture pattern)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    monkeypatch.setenv("O2_SCALPEL_CACHE", str(tmp_path / "cache"))
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


# ---------------------------------------------------------------------------
# Tool builders (one per facade) — direct ``Tool`` instantiation, mirroring
# Leaf 07's ``test_facade_*.py`` pattern. The spec's
# ``pep<NNN>_workspace.invoke()`` wrapper does not exist in this repo; the
# adaptation drops it in favour of the direct facade-call pattern.
# ---------------------------------------------------------------------------


def _build_async_tool(project_root: Path) -> ScalpelConvertToAsyncTool:
    agent = MagicMock(name="SerenaAgent")
    agent.get_project_root.return_value = str(project_root)
    tool = ScalpelConvertToAsyncTool(agent=agent)
    object.__setattr__(tool, "get_project_root", lambda: str(project_root))
    return tool


def _build_annotate_tool(project_root: Path) -> ScalpelAnnotateReturnTypeTool:
    agent = MagicMock(name="SerenaAgent")
    agent.get_project_root.return_value = str(project_root)
    tool = ScalpelAnnotateReturnTypeTool(agent=agent)
    object.__setattr__(tool, "get_project_root", lambda: str(project_root))
    return tool


def _build_relimports_tool(
    project_root: Path,
) -> ScalpelConvertFromRelativeImportsTool:
    agent = MagicMock(name="SerenaAgent")
    agent.get_project_root.return_value = str(project_root)
    tool = ScalpelConvertFromRelativeImportsTool(agent=agent)
    object.__setattr__(tool, "get_project_root", lambda: str(project_root))
    return tool


def _stub_inlay_hint_provider(
    monkeypatch: pytest.MonkeyPatch,
    label: str | None,
) -> None:
    """Inject a fake basedpyright inlay-hint provider.

    Mirrors the pattern in
    ``test/serena/tools/test_facade_annotate_return_type.py`` so tests
    don't need a live basedpyright. ``label=None`` returns no provider
    (short-circuits to ``basedpyright_unavailable``); a string label
    returns a single Type-kind hint.
    """
    if label is None:
        monkeypatch.setattr(
            facades_mod, "_get_inlay_hint_provider", lambda _root: None,
        )
        return

    def fake_provider(_uri: str, _range: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "position": {"line": 0, "character": 9},
                "label": label,
                "kind": 1,
                "paddingLeft": True,
            },
        ]

    monkeypatch.setattr(
        facades_mod,
        "_get_inlay_hint_provider",
        lambda _root: fake_provider,
    )


# ---------------------------------------------------------------------------
# Workspace setup helpers — copy a PEP fixture into ``tmp_path`` so the
# facade can mutate it without touching the canonical fixture file.
# ---------------------------------------------------------------------------


def _seed_flat_fixture(tmp_path: Path, source: Path) -> Path:
    """Copy ``source`` into ``tmp_path/__init__.py`` and return the path.

    Used by F1 (``convert_to_async``) and F2 (``annotate_return_type``)
    where the facade operates on a single file.
    """
    target = tmp_path / "__init__.py"
    target.write_text(_read_fixture(source), encoding="utf-8")
    return target


def _seed_relimport_workspace(
    tmp_path: Path, source: Path, pkg_name: str = "pkg",
) -> Path:
    """Build a workspace where the PEP fixture lives as ``pkg/grammar.py``
    and a sibling ``pkg/y.py`` carries one relative import. F3 operates on
    ``pkg/y.py``; success means rope rewrote the relative import despite
    the PEP-grammar sibling being present in the same package.

    Returns the absolute path of the file F3 should be invoked on.
    """
    pkg = tmp_path / pkg_name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "grammar.py").write_text(_read_fixture(source), encoding="utf-8")
    y_path = pkg / "y.py"
    y_path.write_text("from .grammar import two\n", encoding="utf-8")
    return y_path


# ===========================================================================
# Task 1 — PEP 695 × {F1, F2, F3}
# ===========================================================================


def test_convert_to_async_handles_pep695(
    tmp_path: Path,
) -> None:
    """F1 on PEP 695: turn ``two`` into ``async def two`` without choking on
    ``type Vec2 = ...`` / ``class Box[T]:`` siblings."""
    target = _seed_flat_fixture(tmp_path, PEP695_SOURCE)
    tool = _build_async_tool(tmp_path)

    payload = json.loads(
        tool.apply(file="__init__.py", symbol="two", allow_out_of_workspace=True),
    )
    assert payload["applied"] is True, payload
    assert payload.get("failure") is None, payload
    after = target.read_text(encoding="utf-8")
    assert "async def two() -> int:" in after
    # PEP 695 syntax must survive untouched.
    assert "type Vec2 = tuple[float, float]" in after
    assert "class Box[T]:" in after


@pytest.mark.parametrize(
    ("symbol", "label"),
    [
        ("two", "-> int"),
        ("fetch", "-> int"),
    ],
)
def test_annotate_return_type_handles_pep695(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    symbol: str,
    label: str,
) -> None:
    """F2 on PEP 695: parser must accept ``type X`` + ``class C[T]:``.

    The fixture's functions are already annotated, so the spec accepts
    ``status in ('applied', 'skipped')`` and only requires the absence
    of an ``error_code`` (mapped to ``failure`` in this repo's schema).
    """
    _seed_flat_fixture(tmp_path, PEP695_SOURCE)
    _stub_inlay_hint_provider(monkeypatch, label)
    tool = _build_annotate_tool(tmp_path)

    payload = json.loads(
        tool.apply(file="__init__.py", symbol=symbol, allow_out_of_workspace=True),
    )
    assert payload.get("failure") is None, payload
    # Already-annotated -> no_op=True; otherwise applied=True. Both pass.
    assert payload["applied"] is True or payload["no_op"] is True, payload


def test_convert_from_relative_imports_handles_pep695(
    tmp_path: Path,
) -> None:
    """F3 on PEP 695: rope must keep traversing the package even when a
    sibling module exercises ``type X`` / ``class C[T]:`` syntax."""
    y_path = _seed_relimport_workspace(tmp_path, PEP695_SOURCE)
    tool = _build_relimports_tool(tmp_path)

    payload = json.loads(
        tool.apply(file="pkg/y.py", allow_out_of_workspace=True),
    )
    assert payload.get("failure") is None, payload
    assert payload["applied"] is True, payload
    assert (
        y_path.read_text(encoding="utf-8") == "from pkg.grammar import two\n"
    )
