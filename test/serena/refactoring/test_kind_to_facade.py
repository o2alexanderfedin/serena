"""v1.5 Phase 1 — KIND_TO_FACADE routing-hint contract tests.

Spec: docs/superpowers/specs/2026-04-29-lsp-feature-coverage-spec.md § 3.3.

Asserts:

1. KIND_TO_FACADE has the 8 reconciled (source_server, kind) entries that
   match the family-level kinds carried by the live capability catalog
   (the spec authorizes reconciliation against
   ``capability_catalog_baseline.json``).
2. ``build_capability_catalog`` populates ``preferred_facade`` non-null for
   exactly those (server, kind) tuples and ``None`` for the rest.
3. The lookup is keyed on the **tuple** ``(source_server, kind)``, never on
   ``kind`` alone — kind strings collide across LSPs.
"""

from __future__ import annotations

import pytest

from serena.refactoring import STRATEGY_REGISTRY
from serena.refactoring.capabilities import (
    KIND_TO_FACADE,
    build_capability_catalog,
)


# Reconciled set from the spec § 3.2 table, projected onto the family-level
# kinds the catalog stores. Subfamily kinds (changeVisibility, expandMacro,
# localToField, useFunction, deriveImpl, basedpyright source.organizeImports)
# have no catalog row to populate and are routed at dispatch time by the
# dynamic-capability registry instead.
#
# v1.5 P2 (spec § 4.2) added three jdtls rows for the Java facades.
EXPECTED_ENTRIES: dict[tuple[str, str], str] = {
    # Phase 1 (rust-analyzer + pylsp-rope + ruff):
    ("rust-analyzer", "refactor.extract"): "scalpel_extract",
    ("rust-analyzer", "refactor.inline"): "scalpel_inline",
    ("rust-analyzer", "refactor.rewrite"): "scalpel_change_visibility",
    ("rust-analyzer", "source.organizeImports"): "scalpel_imports_organize",
    ("pylsp-rope", "refactor.extract"): "scalpel_extract",
    ("pylsp-rope", "refactor.inline"): "scalpel_inline",
    ("ruff", "source.fixAll"): "scalpel_fix_lints",
    ("ruff", "source.organizeImports"): "scalpel_imports_organize",
    # Phase 2 (jdtls / Java):
    ("jdtls", "refactor.extract"): "scalpel_extract",
    ("jdtls", "source.generate.constructor"): "scalpel_generate_constructor",
    ("jdtls", "source.generate.overrideMethods"): "scalpel_override_methods",
}


def test_kind_to_facade_constant_matches_spec() -> None:
    """The static table holds exactly the spec-reconciled set."""
    assert dict(KIND_TO_FACADE) == EXPECTED_ENTRIES


@pytest.mark.parametrize(("server", "kind", "facade"), [
    (s, k, f) for (s, k), f in EXPECTED_ENTRIES.items()
])
def test_preferred_facade_populated_for_rust_python_kinds(
    server: str, kind: str, facade: str,
) -> None:
    """Each spec-listed (server, kind) tuple resolves to its named facade
    in the live-introspected catalog.
    """
    catalog = build_capability_catalog(STRATEGY_REGISTRY)
    matching = [
        r for r in catalog.records
        if r.source_server == server and r.kind == kind
    ]
    assert matching, (
        f"no catalog record for ({server!r}, {kind!r}) — KIND_TO_FACADE "
        f"is out of sync with the live capability catalog"
    )
    for record in matching:
        assert record.preferred_facade == facade, (
            f"({server!r}, {kind!r}) record has "
            f"preferred_facade={record.preferred_facade!r}, expected {facade!r}"
        )


def test_preferred_facade_is_none_for_unrouted_records() -> None:
    """Records whose (server, kind) tuple is NOT in KIND_TO_FACADE carry
    ``preferred_facade=None`` — proving the lookup is the only population
    path and there is no silent fallback.
    """
    catalog = build_capability_catalog(STRATEGY_REGISTRY)
    unrouted = [
        r for r in catalog.records
        if (r.source_server, r.kind) not in EXPECTED_ENTRIES
    ]
    assert unrouted, "expected some records to be unrouted (sanity check)"
    for r in unrouted:
        assert r.preferred_facade is None, (
            f"unexpected preferred_facade={r.preferred_facade!r} on "
            f"({r.source_server!r}, {r.kind!r})"
        )


def test_lookup_is_tuple_keyed_not_kind_only() -> None:
    """Asserts the load-bearing tuple-keying contract from spec § 3.2.

    If the table were keyed on ``kind`` alone, then
    (``rust-analyzer``, ``refactor.extract``) and
    (``pylsp-rope``, ``refactor.extract``) would collide. Both must
    resolve independently, even though they happen to share the same
    facade today.
    """
    rust_extract = KIND_TO_FACADE.get(("rust-analyzer", "refactor.extract"))
    py_extract = KIND_TO_FACADE.get(("pylsp-rope", "refactor.extract"))
    assert rust_extract == "scalpel_extract"
    assert py_extract == "scalpel_extract"
    # Wrong-tuple lookup must miss, even with a valid kind half:
    assert KIND_TO_FACADE.get(("rust-analyzer", "refactor.inline")) == "scalpel_inline"
    assert KIND_TO_FACADE.get(("vtsls", "refactor.extract")) is None  # vtsls unrouted
