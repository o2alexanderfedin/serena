"""T3 — _introspect_adapter_kinds reads codeActionKind.valueSet."""

from __future__ import annotations

import pytest


def test_introspect_pylsp_returns_seven_kinds() -> None:
    from serena.refactoring.capabilities import _introspect_adapter_kinds
    from solidlsp.language_servers.pylsp_server import PylspServer

    kinds = _introspect_adapter_kinds(PylspServer, repository_absolute_path="/tmp/x")
    # pylsp_server.py:127-135 advertises:
    # ["", "quickfix", "refactor", "refactor.extract", "refactor.inline",
    #  "refactor.rewrite", "source", "source.organizeImports"] — empty string
    # is filtered by the helper, so 7 kinds.
    assert "" not in kinds
    assert "quickfix" in kinds
    assert "refactor.extract" in kinds
    assert "source.organizeImports" in kinds
    assert len(kinds) == 7


def test_introspect_ruff_returns_four_kinds() -> None:
    from serena.refactoring.capabilities import _introspect_adapter_kinds
    from solidlsp.language_servers.ruff_server import RuffServer

    kinds = _introspect_adapter_kinds(RuffServer, repository_absolute_path="/tmp/x")
    # ruff_server.py:98-104 advertises:
    # ["", "quickfix", "source", "source.organizeImports", "source.fixAll"]
    assert "" not in kinds
    assert kinds == frozenset({"quickfix", "source", "source.organizeImports", "source.fixAll"})


def test_introspect_basedpyright_returns_empty_set() -> None:
    """basedpyright is pull-mode-diagnostics-only; advertises no codeAction kinds.

    Stage 1F treats this as 'attribution falls back to strategy default'
    rather than an error. The helper returns an empty frozenset and the
    factory keeps the strategy-attributed source_server.
    """
    from serena.refactoring.capabilities import _introspect_adapter_kinds
    from solidlsp.language_servers.basedpyright_server import BasedpyrightServer

    kinds = _introspect_adapter_kinds(BasedpyrightServer, repository_absolute_path="/tmp/x")
    assert kinds == frozenset()


def test_introspect_rust_analyzer_returns_nonempty_set() -> None:
    from serena.refactoring.capabilities import _introspect_adapter_kinds
    from solidlsp.language_servers.rust_analyzer import RustAnalyzer

    kinds = _introspect_adapter_kinds(RustAnalyzer, repository_absolute_path="/tmp/x")
    # rust-analyzer's adapter advertises a non-empty kind set; the exact
    # contents are part of the golden baseline (T4) — here we only assert
    # the introspection path works against a non-Python adapter.
    assert isinstance(kinds, frozenset)
    assert len(kinds) > 0


def test_introspect_raises_on_non_static_method() -> None:
    """If a future adapter makes _get_initialize_params an instance method,
    the helper raises CatalogIntrospectionError with an actionable message."""
    from serena.refactoring.capabilities import (
        CatalogIntrospectionError,
        _introspect_adapter_kinds,
    )

    class _BadAdapter:
        def _get_initialize_params(self, repository_absolute_path: str) -> dict:  # type: ignore[no-untyped-def]
            del repository_absolute_path
            return {}

    with pytest.raises(CatalogIntrospectionError) as excinfo:
        _introspect_adapter_kinds(_BadAdapter, repository_absolute_path="/tmp/x")
    assert "staticmethod" in str(excinfo.value)


def test_factory_with_adapters_attributes_ruff_kinds_to_ruff() -> None:
    """T3 factory contract: when an adapter advertises a kind, the catalog
    record for (language, kind) gets that adapter's source_server.

    With the Stage 1E adapter set:
      - ruff advertises source.organizeImports + source.fixAll → those two
        Python kinds become source_server='ruff'.
      - pylsp advertises refactor.extract / refactor.inline / refactor.rewrite
        / quickfix → those Python kinds become source_server='pylsp-rope'.
    """
    from serena.refactoring import STRATEGY_REGISTRY
    from serena.refactoring.capabilities import build_capability_catalog

    cat = build_capability_catalog(STRATEGY_REGISTRY)
    by_id = {r.id: r for r in cat.records}

    # source.organizeImports is in PythonStrategy.code_action_allow_list AND
    # ruff's adapter advertises it; T3 attributes it to ruff.
    assert by_id["python.source.organizeImports"].source_server == "ruff"
    assert by_id["python.source.fixAll"].source_server == "ruff"
    # refactor.extract is in PythonStrategy.code_action_allow_list AND pylsp
    # advertises it; T3 attributes it to pylsp-rope (also the default).
    assert by_id["python.refactor.extract"].source_server == "pylsp-rope"
