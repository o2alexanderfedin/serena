"""v0.2.0-G — CapabilityCatalog.hash() returns SHA-256 of canonical JSON.

Backlog item #8 from MVP cut. Lets external consumers detect catalog drift
without re-serialising the records themselves; the hash is referenced from
``ScalpelRuntime`` telemetry and from the drift CI gate.
"""

from __future__ import annotations

import hashlib
import json

from serena.refactoring.capabilities import CapabilityCatalog, CapabilityRecord


def _record(idx: int) -> CapabilityRecord:
    return CapabilityRecord(
        id=f"test.cap.{idx}",
        language="rust",
        kind="refactor",
        source_server="rust-analyzer",
        params_schema={"file": "string"},
        preferred_facade=None,
        extension_allow_list=frozenset({".rs"}),
    )


def test_catalog_hash_returns_sha256_hex_of_to_json():
    catalog = CapabilityCatalog(records=(_record(1), _record(2)))
    expected = hashlib.sha256(catalog.to_json().encode()).hexdigest()
    assert catalog.hash() == expected
    assert len(catalog.hash()) == 64


def test_catalog_hash_is_deterministic_across_construction_orders():
    """Records re-sort on construction; hash must reflect canonical order."""
    a = CapabilityCatalog(records=(_record(1), _record(2), _record(3)))
    b = CapabilityCatalog(records=(_record(3), _record(1), _record(2)))
    assert a.hash() == b.hash()


def test_catalog_hash_changes_when_records_change():
    a = CapabilityCatalog(records=(_record(1),))
    b = CapabilityCatalog(records=(_record(1), _record(2)))
    assert a.hash() != b.hash()


def test_catalog_hash_round_trips_via_from_json():
    """A catalog reloaded from its own JSON must produce the same hash."""
    original = CapabilityCatalog(records=(_record(1), _record(2)))
    reloaded = CapabilityCatalog.from_json(original.to_json())
    assert reloaded.hash() == original.hash()


def test_empty_catalog_has_stable_hash():
    """Hash of the empty catalog == sha256 of the canonical empty payload."""
    catalog = CapabilityCatalog(records=())
    expected_blob = json.dumps(
        {"schema_version": 1, "records": []},
        indent=2, sort_keys=True, ensure_ascii=True,
    ) + "\n"
    expected_hash = hashlib.sha256(expected_blob.encode()).hexdigest()
    assert catalog.hash() == expected_hash
