"""T2 — build_capability_catalog factory walks STRATEGY_REGISTRY."""

from __future__ import annotations

import pytest


def test_factory_with_real_registry_returns_nonempty_catalog() -> None:
    from serena.refactoring import STRATEGY_REGISTRY
    from serena.refactoring.capabilities import build_capability_catalog

    cat = build_capability_catalog(STRATEGY_REGISTRY)
    assert len(cat.records) > 0


def test_factory_emits_one_record_per_strategy_kind_pair() -> None:
    from serena.refactoring import STRATEGY_REGISTRY, PythonStrategy, RustStrategy
    from serena.refactoring.capabilities import build_capability_catalog

    cat = build_capability_catalog(STRATEGY_REGISTRY)

    # Stage 1E declared 7 Python kinds + 6 Rust kinds. T2 emits one record
    # per (language, kind) pair using the strategy whitelist as the source
    # (T3 will enrich with adapter-advertised kinds, but T2's contract is
    # strategy-driven only).
    py_records = [r for r in cat.records if r.language == "python"]
    rs_records = [r for r in cat.records if r.language == "rust"]
    assert len(py_records) == len(PythonStrategy.code_action_allow_list)
    assert len(rs_records) == len(RustStrategy.code_action_allow_list)


def test_factory_python_records_carry_python_extensions() -> None:
    from serena.refactoring import STRATEGY_REGISTRY
    from serena.refactoring.capabilities import build_capability_catalog

    cat = build_capability_catalog(STRATEGY_REGISTRY)
    py_records = [r for r in cat.records if r.language == "python"]
    for rec in py_records:
        assert rec.extension_allow_list == frozenset({".py", ".pyi"})


def test_factory_rust_records_carry_rust_extensions() -> None:
    from serena.refactoring import STRATEGY_REGISTRY
    from serena.refactoring.capabilities import build_capability_catalog

    cat = build_capability_catalog(STRATEGY_REGISTRY)
    rs_records = [r for r in cat.records if r.language == "rust"]
    for rec in rs_records:
        assert rec.extension_allow_list == frozenset({".rs"})


def test_factory_record_id_format_is_dotted_lang_kind() -> None:
    from serena.refactoring import STRATEGY_REGISTRY
    from serena.refactoring.capabilities import build_capability_catalog

    cat = build_capability_catalog(STRATEGY_REGISTRY)
    for rec in cat.records:
        assert rec.id == f"{rec.language}.{rec.kind}", rec


def test_factory_records_are_sorted() -> None:
    from serena.refactoring import STRATEGY_REGISTRY
    from serena.refactoring.capabilities import build_capability_catalog

    cat = build_capability_catalog(STRATEGY_REGISTRY)
    keys = [(r.language, r.source_server, r.kind, r.id) for r in cat.records]
    assert keys == sorted(keys)


def test_factory_empty_registry_returns_empty_catalog() -> None:
    from serena.refactoring.capabilities import build_capability_catalog

    cat = build_capability_catalog({})
    assert len(cat.records) == 0


def test_factory_python_source_server_is_pylsp_rope_default() -> None:
    """T2 contract: strategy-only walk attributes Python kinds to pylsp-rope.

    T3 will add per-adapter attribution (basedpyright kinds → basedpyright,
    ruff kinds → ruff). T2's job is the strategy-only baseline so the
    delta T3 introduces is reviewable as an isolated commit.
    """
    from serena.refactoring import STRATEGY_REGISTRY
    from serena.refactoring.capabilities import build_capability_catalog

    cat = build_capability_catalog(STRATEGY_REGISTRY)
    for rec in cat.records:
        if rec.language == "python":
            assert rec.source_server == "pylsp-rope"
        elif rec.language == "rust":
            assert rec.source_server == "rust-analyzer"
        else:
            pytest.fail(f"unexpected language: {rec.language}")
