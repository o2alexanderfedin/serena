"""T13 — aggregate wall-clock budget assertion for the Stage 2B E2E suite.

Per scope-report S16.4: full E2E suite <= 12 min on CI runner.

Reads the per-test elapsed-time bucket populated by the `wall_clock_record`
fixture in conftest.py. Hard-fails when O2_SCALPEL_E2E_BUDGET_ASSERT=1.
"""

from __future__ import annotations

import os

import pytest

from test.e2e.conftest import get_wall_clock_bucket  # type: ignore[import-not-found]


WALL_CLOCK_BUDGET_SECONDS = 720.0  # 12 min cap (scope-report S16.4)
PER_SCENARIO_SOFT_BUDGET = {
    "test_e1_rust_4way_split_byte_identical": 240.0,
    "test_e1_py_4way_split_byte_identical": 120.0,
    "test_e9_rust_semantic_equivalence": 240.0,
    "test_e9_py_semantic_equivalence": 180.0,
    "test_e2_extract_dry_run_matches_commit": 60.0,
    "test_e3_rollback_restores_python_tree": 60.0,
    "test_e10_rust_rename_across_modules": 180.0,
    "test_e10_py_rename_preserves_dunder_all": 60.0,
    "test_e13_py_organize_imports_single_action": 60.0,
    "test_e11_split_to_outside_workspace_path_rejected": 30.0,
    "test_e12_transaction_commit_then_rollback_round_trip": 120.0,
    "test_e12_inline_round_trip_with_checkpoint_replay": 120.0,
    "test_diagnostic_count_calcpy": 30.0,
}


@pytest.mark.e2e
def test_zzz_wall_clock_budget() -> None:
    bucket = list(get_wall_clock_bucket())
    if not bucket:
        pytest.skip("no wall_clock_record entries collected; nothing to budget")

    total = sum(seconds for _, seconds in bucket)
    print("\n--- Stage 2B wall-clock breakdown ---")
    for name, seconds in sorted(bucket, key=lambda kv: -kv[1]):
        soft = PER_SCENARIO_SOFT_BUDGET.get(name)
        marker = ""
        if soft is not None and seconds > soft:
            marker = f" SOFT-OVERRUN (soft={soft:.0f}s)"
        print(f"  {seconds:7.2f}s  {name}{marker}")
    print(f"--- TOTAL: {total:.2f}s (cap={WALL_CLOCK_BUDGET_SECONDS:.0f}s) ---")

    if os.environ.get("O2_SCALPEL_E2E_BUDGET_ASSERT") != "1":
        pytest.skip(
            "budget assertion gated; set O2_SCALPEL_E2E_BUDGET_ASSERT=1 on CI"
        )

    assert total <= WALL_CLOCK_BUDGET_SECONDS, (
        f"Stage 2B E2E aggregate wall-clock {total:.2f}s exceeds the "
        f"{WALL_CLOCK_BUDGET_SECONDS:.0f}s cap (scope-report S16.4)."
    )
