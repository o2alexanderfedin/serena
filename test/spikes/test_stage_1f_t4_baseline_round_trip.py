"""T4 — golden-file baseline round-trip + --update-catalog-baseline UX."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_baseline_path_fixture_returns_repo_relative_path(
    capability_catalog_baseline_path: Path,
) -> None:
    assert capability_catalog_baseline_path.name == "capability_catalog_baseline.json"
    assert capability_catalog_baseline_path.parent.name == "data"
    assert capability_catalog_baseline_path.parent.parent.name == "spikes"


def test_baseline_file_is_checked_in(
    capability_catalog_baseline_path: Path,
) -> None:
    assert capability_catalog_baseline_path.exists(), (
        "capability_catalog_baseline.json missing; run "
        "pytest test/spikes/test_stage_1f_t5_catalog_drift.py "
        "--update-catalog-baseline"
    )


def test_baseline_round_trip_through_catalog(
    capability_catalog_baseline_path: Path,
) -> None:
    from serena.refactoring.capabilities import CapabilityCatalog

    blob = capability_catalog_baseline_path.read_text(encoding="utf-8")
    cat = CapabilityCatalog.from_json(blob)
    reblob = cat.to_json()
    assert blob == reblob, (
        "baseline file is not in canonical form; re-baseline via "
        "pytest --update-catalog-baseline"
    )


def test_baseline_schema_version_is_one(
    capability_catalog_baseline_path: Path,
) -> None:
    payload = json.loads(capability_catalog_baseline_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1


def test_baseline_records_are_sorted(
    capability_catalog_baseline_path: Path,
) -> None:
    payload = json.loads(capability_catalog_baseline_path.read_text(encoding="utf-8"))
    keys = [
        (r["language"], r["source_server"], r["kind"], r["id"])
        for r in payload["records"]
    ]
    assert keys == sorted(keys)


def test_baseline_record_count_matches_live_catalog(
    capability_catalog_baseline_path: Path,
) -> None:
    """Sanity-check: baseline cardinality equals live-introspected cardinality.

    Pure cardinality — drift content is checked in T5. This test catches
    'someone added a strategy kind without re-baselining'.
    """
    from serena.refactoring import STRATEGY_REGISTRY
    from serena.refactoring.capabilities import build_capability_catalog

    live = build_capability_catalog(STRATEGY_REGISTRY)
    payload = json.loads(capability_catalog_baseline_path.read_text(encoding="utf-8"))
    assert len(live.records) == len(payload["records"]), (
        f"live catalog has {len(live.records)} records, baseline has "
        f"{len(payload['records'])}; re-baseline via "
        f"pytest --update-catalog-baseline"
    )


def test_regenerate_baseline_when_flag_set(
    capability_catalog_baseline_path: Path,
    update_catalog_baseline_requested: bool,
) -> None:
    """When --update-catalog-baseline is passed, regenerate the file.

    Without the flag, the test SKIPs (so normal test runs are silent).
    With the flag, the file is rewritten and the test passes; the human
    then commits the regenerated file.
    """
    if not update_catalog_baseline_requested:
        pytest.skip("pass --update-catalog-baseline to regenerate")

    from serena.refactoring import STRATEGY_REGISTRY
    from serena.refactoring.capabilities import build_capability_catalog

    cat = build_capability_catalog(STRATEGY_REGISTRY)
    capability_catalog_baseline_path.parent.mkdir(parents=True, exist_ok=True)
    capability_catalog_baseline_path.write_text(cat.to_json(), encoding="utf-8")
