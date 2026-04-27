"""E2E scenario E1-py — split calcpy_e2e/calcpy/calcpy.py into 4 sibling modules.

Maps to scope-report S15.1 row E1-py: "Split `calcpy/calcpy.py` into
ast/errors/parser/evaluator. `pytest -q` byte-identical".
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest


def _run_pytest_q(project_root: Path, python_bin: str) -> tuple[int, str]:
    proc = subprocess.run(
        [python_bin, "-m", "pytest", "-q", "tests"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        timeout=120,
        env={
            "PYTHONPATH": str(project_root),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        },
    )
    keep: list[str] = []
    for line in proc.stdout.splitlines():
        if "passed" in line or "failed" in line or "error" in line:
            # v0.2.0-H: strip wall-clock timing ("in 0.05s") so byte-identity
            # checks don't flake on full-suite re-runs where the host is busier.
            keep.append(re.sub(r"\s+in\s+\d+(?:\.\d+)?s\b", "", line))
    return proc.returncode, "\n".join(keep)


@pytest.mark.e2e
def test_e1_py_4way_split_byte_identical(
    mcp_driver_python,
    calcpy_e2e_root: Path,
    python_bin: str,
    wall_clock_record,
) -> None:
    del wall_clock_record
    src = calcpy_e2e_root / "calcpy" / "calcpy.py"
    init = calcpy_e2e_root / "calcpy" / "__init__.py"
    assert src.exists(), "baseline calcpy.py missing"
    assert init.exists()

    pre_rc, pre_stdout = _run_pytest_q(calcpy_e2e_root, python_bin)
    assert pre_rc == 0, f"baseline pytest failed: rc={pre_rc}\n{pre_stdout}"

    result_json = mcp_driver_python.split_file(
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
    payload = json.loads(result_json)

    # v0.2.0 followup-05: this used to fall back to ``pytest.skip`` when
    # ``applied`` came back False, masking the Stage 2B flake. Leaf 05's
    # 30-run diagnostic harness (test/e2e/_e1_py_diagnostic.py) recorded
    # 30/30 successful applies on this host, so the skip path is dead
    # weight. Demand applied=True unconditionally so any future regression
    # fails loudly; the dedicated determinism guard lives in
    # test_e2e_e1_py_determinism.py.
    assert payload.get("applied") is True, (
        f"E1-py split must apply deterministically; got payload={payload!r}"
    )
    assert payload.get("checkpoint_id"), (
        f"applied=true but no checkpoint_id: {payload}"
    )
    # __all__ preservation check (load-bearing for E10-py too).
    init_text = init.read_text(encoding="utf-8")
    for name in ("CalcError", "DivisionByZero", "Expr", "evaluate", "parse"):
        assert name in init_text, f"__all__ lost {name!r} after split"

    post_rc, post_stdout = _run_pytest_q(calcpy_e2e_root, python_bin)
    assert post_rc == 0, (
        f"post-split pytest failed: rc={post_rc}\n{post_stdout}"
    )
    assert post_stdout == pre_stdout, (
        f"pytest -q stdout drifted across split:\n"
        f"--- pre ---\n{pre_stdout}\n--- post ---\n{post_stdout}"
    )


@pytest.mark.e2e
def test_e1_py_split_preview_token_round_trip(
    mcp_driver_python,
    calcpy_e2e_root: Path,
) -> None:
    src = calcpy_e2e_root / "calcpy" / "calcpy.py"
    pre_bytes = src.read_bytes()

    dry = mcp_driver_python.split_file(
        file=str(src),
        groups={"ast": ["Num"], "errors": ["CalcError"]},
        dry_run=True,
        language="python",
    )
    dry_payload = json.loads(dry)
    assert dry_payload.get("applied") is False, "dry_run=True must not apply"
    # On-disk file unchanged on dry-run.
    assert src.read_bytes() == pre_bytes, "dry_run=True modified the file"
