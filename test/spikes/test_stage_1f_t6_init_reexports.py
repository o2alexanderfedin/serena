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
    # Cardinality grows whenever a Stream-6+ strategy adds an allow-list
    # entry. Smoke-check the lower bound (post-v1.4 polyglot surface) and
    # assert the language set is exactly the registered strategies — the
    # exact-record count is enforced by the drift CI in
    # test_stage_1f_t4_baseline_round_trip.
    assert len(cat.records) >= 26
    languages = sorted({r.language for r in cat.records})
    expected_languages = sorted({s.language_id for s in STRATEGY_REGISTRY.values()})
    # markdown ships strategies but marksman exposes no code-action kinds,
    # so it does not contribute records.
    expected_with_records = [
        lang for lang in expected_languages if lang != "markdown"
    ]
    assert languages == expected_with_records
