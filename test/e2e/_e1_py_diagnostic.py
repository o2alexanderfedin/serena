"""Instrumentation harness for the E1-py flake (Leaf 05 / followup-05).

Original Stage 2B observation: ``ScalpelSplitFileTool.apply`` against the
calcpy fixture occasionally returned ``applied=False`` with a stale
``failure`` payload. The original test guarded against the flake with
``pytest.skip``; Leaf 05 replaces that with a hard assertion. This
module is the offline diagnostic that produced the empirical pass-rate
ledger justifying the strip-the-skip change.

Usage (one-off, not part of the standard pytest suite)::

    from pathlib import Path
    from test.e2e._e1_py_diagnostic import collect, write_ledger

    ledger = collect(driver, Path("/tmp/calcpy_e2e/calcpy/calcpy.py"), n=30)
    write_ledger(ledger)

The harness records, per run:
  * ``elapsed_s`` — wall-clock for the dispatch round-trip
  * ``applied`` — flag returned by the facade
  * ``failure`` — failure-reason string (None on success)
  * ``checkpoint_id`` — checkpoint persisted on success

Drops a JSON ledger at ``/tmp/e1py-flake-<timestamp>.json`` for offline
analysis. Likely root-cause hypotheses (TRIZ — segmentation: split the
apply path from the discover path):

  1. basedpyright pull-mode race — pull arrives after merge, downgrading
     actions to a stale subset (P4 spike).
  2. Stale source-map in pylsp-rope — file watcher hasn't fired after a
     prior test mutated calcpy.py.
  3. Checkpoint LRU eviction — applied=False because the previous
     checkpoint's edit set was evicted before apply_workspace_edit.

Author: AI Hive(R).
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any


def run_one(driver: Any, src: Path) -> dict[str, Any]:
    """Run a single split dispatch; return a per-run telemetry dict."""
    t0 = time.perf_counter()
    payload = json.loads(
        driver.split_file(
            file=str(src),
            groups={
                "ast": ["Num", "Add", "Sub", "Mul", "Div", "Expr"],
                "errors": ["CalcError", "ParseError", "DivisionByZero"],
                "parser": ["parse"],
                "evaluator": ["evaluate"],
            },
            parent_layout="file",
            reexport_policy="preserve_public_api",
            dry_run=False,
            language="python",
        )
    )
    return {
        "elapsed_s": time.perf_counter() - t0,
        "applied": payload.get("applied"),
        "failure": payload.get("failure"),
        "checkpoint_id": payload.get("checkpoint_id"),
    }


def collect(driver: Any, src: Path, n: int = 30) -> list[dict[str, Any]]:
    """Run ``run_one`` ``n`` times back-to-back and return the ledger list."""
    return [run_one(driver, src) for _ in range(n)]


def summarize(ledger: list[dict[str, Any]]) -> dict[str, Any]:
    """Reduce the per-run ledger into pass/fail counts and percentile timings.

    Percentiles use ``statistics.quantiles(n=100, method="exclusive")`` —
    the standard library's correct percentile math (linear interpolation
    between order statistics). The earlier ad-hoc indexing
    (``elapsed[total // 2]``, ``elapsed[int(total * 0.99) - 1]``)
    silently mislabels: for ``total=30`` the old p50 was the 16th order
    statistic (upper median, not the median) and the old p99 was the
    29th order statistic — actually the 96.7th percentile.
    """
    total = len(ledger)
    applied = sum(1 for row in ledger if row.get("applied") is True)
    failures = [row for row in ledger if row.get("applied") is not True]
    elapsed = sorted(float(row["elapsed_s"]) for row in ledger)
    if total >= 2:
        # quantiles(n=100) returns 99 cut points (1st through 99th percentile).
        quantile_points = statistics.quantiles(elapsed, n=100, method="exclusive")
        p50 = quantile_points[49]
        p99 = quantile_points[98]
    elif total == 1:
        p50 = p99 = elapsed[0]
    else:
        p50 = p99 = 0.0
    return {
        "total_runs": total,
        "applied_runs": applied,
        "applied_rate": (applied / total) if total else 0.0,
        "failure_rows": failures,
        "elapsed_p50_s": p50,
        "elapsed_p99_s": p99,
    }


def write_ledger(
    ledger: list[dict[str, Any]],
    *,
    out_dir: Path = Path("/tmp"),
) -> Path:
    """Persist the ledger as JSON keyed by perf-counter timestamp; return path."""
    stamp = int(time.time())
    out = out_dir / f"e1py-flake-{stamp}.json"
    out.write_text(
        json.dumps(
            {"ledger": ledger, "summary": summarize(ledger)},
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return out
