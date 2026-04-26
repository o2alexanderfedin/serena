"""T2 — ScalpelRuntime singleton: lazy catalog, per-language pool, reset."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _reset_runtime() -> Iterator[None]:
    from serena.tools.scalpel_runtime import ScalpelRuntime

    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def test_singleton_is_idempotent() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime

    a = ScalpelRuntime.instance()
    b = ScalpelRuntime.instance()
    assert a is b


def test_catalog_is_lazy_and_cached() -> None:
    from serena.refactoring.capabilities import CapabilityCatalog
    from serena.tools.scalpel_runtime import ScalpelRuntime

    rt = ScalpelRuntime.instance()
    cat_a = rt.catalog()
    cat_b = rt.catalog()
    assert isinstance(cat_a, CapabilityCatalog)
    assert cat_a is cat_b  # cached, identity-equal


def test_checkpoint_store_lru_50() -> None:
    from serena.refactoring import CheckpointStore
    from serena.tools.scalpel_runtime import ScalpelRuntime

    store = ScalpelRuntime.instance().checkpoint_store()
    assert isinstance(store, CheckpointStore)
    # Stage 1B precedent: default capacity 50.
    assert store._capacity == 50  # type: ignore[attr-defined]


def test_transaction_store_lru_20_and_bound_to_checkpoint_store() -> None:
    from serena.refactoring import TransactionStore
    from serena.tools.scalpel_runtime import ScalpelRuntime

    rt = ScalpelRuntime.instance()
    txn_store = rt.transaction_store()
    assert isinstance(txn_store, TransactionStore)
    assert txn_store._capacity == 20  # type: ignore[attr-defined]
    # Bound to the same checkpoint store the runtime exposes.
    assert txn_store._checkpoints is rt.checkpoint_store()  # type: ignore[attr-defined]


def test_pool_for_returns_same_instance_per_key(tmp_path: Path) -> None:
    from solidlsp.ls_config import Language

    from serena.tools.scalpel_runtime import ScalpelRuntime

    rt = ScalpelRuntime.instance()
    pool_a = rt.pool_for(Language.PYTHON, tmp_path)
    pool_b = rt.pool_for(Language.PYTHON, tmp_path)
    assert pool_a is pool_b


def test_pool_for_returns_distinct_instance_per_language(tmp_path: Path) -> None:
    from solidlsp.ls_config import Language

    from serena.tools.scalpel_runtime import ScalpelRuntime

    rt = ScalpelRuntime.instance()
    py = rt.pool_for(Language.PYTHON, tmp_path)
    rs = rt.pool_for(Language.RUST, tmp_path)
    assert py is not rs


def test_reset_for_testing_clears_singleton(tmp_path: Path) -> None:
    del tmp_path
    from serena.tools.scalpel_runtime import ScalpelRuntime

    a = ScalpelRuntime.instance()
    a.checkpoint_store()  # touch lazy state
    ScalpelRuntime.reset_for_testing()
    b = ScalpelRuntime.instance()
    assert a is not b
