"""T1 — CapabilityRecord + CapabilityCatalog schema tests."""

from __future__ import annotations

import json
from typing import get_args

import pytest
from pydantic import ValidationError


def test_capability_record_imports() -> None:
    from serena.refactoring.capabilities import CapabilityCatalog, CapabilityRecord

    del CapabilityRecord
    del CapabilityCatalog


def test_capability_record_required_fields() -> None:
    from serena.refactoring.capabilities import CapabilityRecord

    rec = CapabilityRecord(
        id="python.refactor.extract",
        language="python",
        kind="refactor.extract",
        source_server="pylsp-rope",
        params_schema={"type": "object"},
        preferred_facade=None,
        extension_allow_list=frozenset({".py", ".pyi"}),
    )
    assert rec.id == "python.refactor.extract"
    assert rec.language == "python"
    assert rec.kind == "refactor.extract"
    assert rec.source_server == "pylsp-rope"
    assert rec.params_schema == {"type": "object"}
    assert rec.preferred_facade is None
    assert rec.extension_allow_list == frozenset({".py", ".pyi"})


def test_capability_record_source_server_is_provenance_literal() -> None:
    from serena.refactoring.capabilities import CapabilityRecord
    from serena.refactoring.multi_server import ProvenanceLiteral

    legal = set(get_args(ProvenanceLiteral))
    # Stage 1F constraint: source_server MUST be a member of the closed
    # ProvenanceLiteral set so the catalog and the merger speak the same
    # vocabulary.
    for legal_value in legal:
        CapabilityRecord(
            id=f"x.{legal_value}",
            language="python",
            kind="quickfix",
            source_server=legal_value,
            params_schema={},
            preferred_facade=None,
            extension_allow_list=frozenset({".py"}),
        )

    with pytest.raises(ValidationError):
        CapabilityRecord(
            id="x.bogus",
            language="python",
            kind="quickfix",
            source_server="bogus-server",  # type: ignore[arg-type]
            params_schema={},
            preferred_facade=None,
            extension_allow_list=frozenset({".py"}),
        )


def test_capability_record_is_frozen() -> None:
    from serena.refactoring.capabilities import CapabilityRecord

    rec = CapabilityRecord(
        id="python.quickfix",
        language="python",
        kind="quickfix",
        source_server="ruff",
        params_schema={},
        preferred_facade=None,
        extension_allow_list=frozenset({".py"}),
    )
    with pytest.raises(ValidationError):
        rec.id = "tampered"  # type: ignore[misc]


def test_capability_catalog_sorted_records_invariant() -> None:
    from serena.refactoring.capabilities import CapabilityCatalog, CapabilityRecord

    a = CapabilityRecord(
        id="python.zzz",
        language="python",
        kind="quickfix",
        source_server="ruff",
        params_schema={},
        preferred_facade=None,
        extension_allow_list=frozenset({".py"}),
    )
    b = CapabilityRecord(
        id="python.aaa",
        language="python",
        kind="quickfix",
        source_server="basedpyright",
        params_schema={},
        preferred_facade=None,
        extension_allow_list=frozenset({".py"}),
    )
    cat = CapabilityCatalog(records=(a, b))
    # The container reorders to the canonical sort key
    # (language, source_server, kind, id) so the JSON baseline is diff-stable.
    ids = [r.id for r in cat.records]
    assert ids == ["python.aaa", "python.zzz"]


def test_capability_catalog_to_from_json_round_trip() -> None:
    from serena.refactoring.capabilities import CapabilityCatalog, CapabilityRecord

    rec = CapabilityRecord(
        id="rust.refactor.extract",
        language="rust",
        kind="refactor.extract",
        source_server="rust-analyzer",
        params_schema={"type": "object"},
        preferred_facade=None,
        extension_allow_list=frozenset({".rs"}),
    )
    cat = CapabilityCatalog(records=(rec,))
    blob = cat.to_json()
    reloaded = CapabilityCatalog.from_json(blob)
    assert reloaded == cat
    assert blob.endswith("\n"), "JSON output must end in newline for POSIX text-file rules"


def test_capability_catalog_to_json_is_byte_stable() -> None:
    from serena.refactoring.capabilities import CapabilityCatalog, CapabilityRecord

    rec = CapabilityRecord(
        id="python.source.organizeImports",
        language="python",
        kind="source.organizeImports",
        source_server="ruff",
        params_schema={},
        preferred_facade=None,
        extension_allow_list=frozenset({".py", ".pyi"}),
    )
    cat = CapabilityCatalog(records=(rec,))
    blob_a = cat.to_json()
    blob_b = cat.to_json()
    assert blob_a == blob_b
    parsed = json.loads(blob_a)
    # sort_keys=True at the JSON level: top-level keys ascending.
    assert list(parsed.keys()) == sorted(parsed.keys())
