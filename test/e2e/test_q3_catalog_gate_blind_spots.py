"""Q3 — catalog-gate blind-spot fixtures.

Per scope-report S15.4a:
  - test_action_title_stability snapshots literal title strings basedpyright
    emits for the four MVP action kinds.
  - test_diagnostic_count_calcpy asserts basedpyright emits <= N diagnostics
    on the calcpy_e2e baseline (catches v1.32.0 / v1.39.0-style drift).

Both are MVP gates on every basedpyright bump.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

BASELINES_DIR = Path(__file__).parent / "baselines"
ACTION_TITLES_BASELINE = BASELINES_DIR / "basedpyright_action_titles.json"
DIAG_COUNT_BASELINE = BASELINES_DIR / "basedpyright_diagnostic_count.json"


@pytest.mark.e2e
def test_action_title_stability_baseline_loads(
    calcpy_e2e_root: Path,
) -> None:
    """Baseline JSON parses and has the 4 MVP action kinds.

    Live-LSP comparison is the next step (depends on facade preview surface
    populating action titles); for Stage 2B the gate is parseable + ground
    truth captured. Drift-detection wires up once the engine routes preview
    actions back through the facade.
    """
    del calcpy_e2e_root
    baseline = json.loads(ACTION_TITLES_BASELINE.read_text(encoding="utf-8"))
    assert baseline["schema_version"] == 1
    assert "basedpyright_version" in baseline
    kinds = baseline["action_kinds"]
    for k in (
        "source.organizeImports",
        "quickfix.basedpyright.autoimport",
        "quickfix.basedpyright.pyrightignore",
        "source.organizeImports.basedpyright",
    ):
        assert k in kinds, f"missing action kind in baseline: {k}"
        assert kinds[k]["title"]
        assert kinds[k]["description"]


@pytest.mark.e2e
def test_diagnostic_count_calcpy(
    mcp_driver_python,
    calcpy_e2e_root: Path,
    wall_clock_record,
) -> None:
    """basedpyright must emit <= N diagnostics on the clean baseline."""
    del wall_clock_record, calcpy_e2e_root
    baseline = json.loads(DIAG_COUNT_BASELINE.read_text(encoding="utf-8"))
    max_diag = baseline["max_diagnostics"]

    health_json = mcp_driver_python.workspace_health()
    health = json.loads(health_json)
    by_server = health.get("diagnostics_by_server") or {}
    bp_count = by_server.get("basedpyright", 0)

    assert bp_count <= max_diag, (
        f"basedpyright {baseline['basedpyright_version']} emitted {bp_count} "
        f"diagnostics on calcpy_e2e (baseline <= {max_diag}). "
        f"Either fix the fixture or re-baseline."
    )
