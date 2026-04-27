"""E2E determinism guard for the E1-py 4-way split (Leaf 05 / followup-05).

Stage 2B observed an intermittent ``applied=False`` from the split-file
facade against the calcpy fixture, prompting the original test to fall
back to ``pytest.skip`` (see ``test_e2e_e1_py_split_file_python.py``
post-fix history). This module locks the contract by running the
identical 4-way split ten times in a row and demanding ``applied=True``
on every iteration. A single failure is loud and points at the failure
payload so the next regression cannot hide behind a skip.

Author: AI Hive(R).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


@pytest.mark.e2e
@pytest.mark.parametrize("run_index", list(range(10)))
def test_e1_py_split_applies_every_run(
    mcp_driver_python: Any,
    calcpy_e2e_root: Path,
    run_index: int,
) -> None:
    """Run the canonical 4-way split 10 times; demand applied=True each time."""
    src = calcpy_e2e_root / "calcpy" / "calcpy.py"
    assert src.exists(), "baseline calcpy.py missing"

    payload = json.loads(
        mcp_driver_python.split_file(
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
    assert payload.get("applied") is True, (
        f"run {run_index}: applied=False; "
        f"failure={payload.get('failure')!r}; full payload={payload!r}"
    )
    assert payload.get("checkpoint_id"), (
        f"run {run_index}: applied=true but no checkpoint_id: {payload!r}"
    )
