"""T6 — Stage 1F symbols re-exported from serena.refactoring."""

from __future__ import annotations


def test_capability_record_reexported() -> None:
    from serena.refactoring import CapabilityRecord

    del CapabilityRecord


def test_capability_catalog_reexported() -> None:
    from serena.refactoring import CapabilityCatalog

    del CapabilityCatalog


def test_build_capability_catalog_reexported() -> None:
    from serena.refactoring import build_capability_catalog

    del build_capability_catalog


def test_catalog_introspection_error_reexported() -> None:
    from serena.refactoring import CatalogIntrospectionError

    del CatalogIntrospectionError


def test_smoke_build_catalog_via_top_level_import() -> None:
    from serena.refactoring import STRATEGY_REGISTRY, build_capability_catalog

    cat = build_capability_catalog(STRATEGY_REGISTRY)
    # 7 python + 6 rust + 13 typescript (Stream 6 / Leaf A); markdown has 0
    # code-action rows (marksman exposes no codeAction provider).
    assert len(cat.records) == 26
    languages = sorted({r.language for r in cat.records})
    assert languages == ["python", "rust", "typescript"]
