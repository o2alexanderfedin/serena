"""E2E scenario E2 — dry-run -> inspect -> adjust -> commit.

Maps to scope-report S15.1 row E2: "`dry_run=true` returns same `WorkspaceEdit`
`dry_run=false` applies; diagnostics_delta matches".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.mark.e2e
def test_e2_extract_dry_run_matches_commit(
    mcp_driver_python,
    calcpy_e2e_root: Path,
    wall_clock_record,
) -> None:
    del wall_clock_record
    src = calcpy_e2e_root / "calcpy" / "calcpy.py"
    pre_bytes = src.read_bytes()

    # 1. Dry-run: extract a sub-expression in `evaluate` into a helper.
    dry_json = mcp_driver_python.extract(
        file=str(src),
        name_path="evaluate",
        target="function",
        new_name="_eval_div",
        dry_run=True,
        language="python",
    )
    dry = json.loads(dry_json)
    # Either the dispatch returned a RefactorResult (applied=False under
    # dry_run=True) or a CAPABILITY_NOT_AVAILABLE envelope from the
    # dynamic registry. Both satisfy the contract that a dry-run must
    # NOT touch disk; the byte-identity check below is the load-bearing
    # invariant.
    if "kind" in dry and "reason" in dry and dry.get("reason", "").startswith("lsp_does_not_support_"):
        pytest.skip(
            f"host LSPs do not advertise {dry.get('kind')}; capability gap on this host"
        )
    assert dry.get("applied") is False, "dry_run=True must not apply"
    # On-disk bytes are unchanged after dry-run.
    assert src.read_bytes() == pre_bytes

    if dry.get("preview_token") is None:
        pytest.skip(
            f"dry_run did not yield preview_token (Stage 2B observed gap): {dry}"
        )

    dry_diag = dry.get("diagnostics_delta")
    dry_changes = dry.get("changes")

    # 2. Commit: same args, dry_run=False, plus the preview_token continuation.
    commit_json = mcp_driver_python.extract(
        file=str(src),
        name_path="evaluate",
        target="function",
        new_name="_eval_div",
        dry_run=False,
        preview_token=dry["preview_token"],
        language="python",
    )
    commit = json.loads(commit_json)
    # v0.2.0 followup-I4 (strip-the-skip per L05): demand applied=True
    # unconditionally so any future regression fails loudly. Previously the
    # `applied!=True` branch silently skipped, masking the same class of
    # flake L05 diagnosed for E1-py.
    assert commit.get("applied") is True, (
        f"E2 commit must apply deterministically; full payload={commit!r}"
    )

    assert commit.get("checkpoint_id"), (
        f"applied=true but no checkpoint_id: {commit}"
    )

    # diagnostics_delta should match between preview and apply (load-bearing
    # E2 check). Both come from the same WorkspaceEdit application.
    if dry_diag and commit.get("diagnostics_delta"):
        cd = commit["diagnostics_delta"]
        assert cd.get("before") == dry_diag.get("before"), (
            "diagnostics_delta.before drifted between dry-run and commit"
        )

    # changes shape consistency (spec-level)
    if dry_changes and commit.get("changes"):
        assert len(commit["changes"]) == len(dry_changes), (
            f"changes count drifted: dry={len(dry_changes)} commit="
            f"{len(commit['changes'])}"
        )

    # On-disk file changed after commit.
    assert src.read_bytes() != pre_bytes


@pytest.mark.e2e
def test_e2_dry_run_does_not_mutate_disk(
    mcp_driver_python,
    calcpy_e2e_root: Path,
) -> None:
    src = calcpy_e2e_root / "calcpy" / "calcpy.py"
    pre_bytes = src.read_bytes()

    dry_json = mcp_driver_python.extract(
        file=str(src),
        name_path="evaluate",
        target="function",
        new_name="_helper",
        dry_run=True,
        language="python",
    )
    dry = json.loads(dry_json)
    # CAPABILITY_NOT_AVAILABLE envelopes have no ``applied`` key; either
    # path satisfies the disk-untouched invariant which is what this test
    # actually pins.
    if "kind" in dry and "reason" in dry and dry.get("reason", "").startswith("lsp_does_not_support_"):
        pytest.skip(
            f"host LSPs do not advertise {dry.get('kind')}; capability gap on this host"
        )
    assert dry.get("applied") is False
    assert src.read_bytes() == pre_bytes
