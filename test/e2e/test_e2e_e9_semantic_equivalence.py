"""E2E scenarios E9 + E9-py — semantic equivalence (dual-lane).

Maps to scope-report S15.1 rows E9/E9-py: "Pre/post-refactor `cargo test` /
`pytest --doctest-modules` byte-identical on `calcrs` and `calcpy`".
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


def _count_pytest(stdout: str) -> tuple[int, int]:
    """Parse pytest summary line for (passed, failed)."""
    passed = failed = 0
    for line in stdout.splitlines():
        for tok in line.replace(",", "").split():
            if tok.endswith("passed"):
                pass
        # Lines like "4 passed in 0.05s" or "3 passed, 1 failed in ..."
        toks = line.replace(",", "").split()
        for i, tok in enumerate(toks):
            if tok == "passed" and i > 0 and toks[i - 1].isdigit():
                passed += int(toks[i - 1])
            elif tok == "failed" and i > 0 and toks[i - 1].isdigit():
                failed += int(toks[i - 1])
    return passed, failed


def _run_pytest_doctest(root: Path, python_bin: str) -> tuple[int, int, int]:
    proc = subprocess.run(
        [python_bin, "-m", "pytest", "-q", "--doctest-modules", "calcpy", "tests"],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=120,
        env={
            "PYTHONPATH": str(root),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        },
    )
    passed, failed = _count_pytest(proc.stdout)
    return proc.returncode, passed, failed


def _run_cargo_test(root: Path, cargo_bin: str) -> tuple[int, int, int]:
    proc = subprocess.run(
        [cargo_bin, "test", "--quiet"],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=180,
    )
    passed = failed = 0
    for line in proc.stdout.splitlines():
        if line.startswith("test result:"):
            parts = line.split()
            for i, tok in enumerate(parts):
                if tok == "passed;" and i > 0:
                    try:
                        passed += int(parts[i - 1])
                    except ValueError:
                        pass
                elif tok == "failed;" and i > 0:
                    try:
                        failed += int(parts[i - 1])
                    except ValueError:
                        pass
    return proc.returncode, passed, failed


@pytest.mark.e2e
def test_e9_rust_semantic_equivalence(
    mcp_driver_rust,
    calcrs_e2e_root: Path,
    cargo_bin: str,
    rust_analyzer_bin: str,
    wall_clock_record,
) -> None:
    del rust_analyzer_bin, wall_clock_record
    lib_rs = calcrs_e2e_root / "src" / "lib.rs"
    pre_rc, pre_pass, pre_fail = _run_cargo_test(calcrs_e2e_root, cargo_bin)
    if pre_rc != 0:
        pytest.skip(
            f"cargo test baseline broken on this host (rc={pre_rc}); "
            f"E9 cannot be exercised."
        )
    assert pre_pass == 4 and pre_fail == 0

    split_json = mcp_driver_rust.split_file(
        file=str(lib_rs),
        groups={
            "ast": ["Expr"], "errors": ["CalcError"],
            "parser": ["parse"], "eval": ["eval"],
        },
        parent_layout="file",
        reexport_policy="preserve_public_api",
        dry_run=False,
        language="rust",
    )
    split = json.loads(split_json)
    # v0.2.0 followup-I4 (strip-the-skip per L05): demand applied=True
    # unconditionally; the prior skip masked Stage 2B regressions.
    assert split.get("applied") is True, (
        f"E9 Rust split must apply deterministically; full payload={split!r}"
    )

    post_rc, post_pass, post_fail = _run_cargo_test(calcrs_e2e_root, cargo_bin)
    assert post_rc == 0
    assert (post_pass, post_fail) == (pre_pass, pre_fail), (
        f"semantic drift on calcrs: pre=({pre_pass},{pre_fail}) "
        f"post=({post_pass},{post_fail})"
    )


@pytest.mark.e2e
def test_e9_py_semantic_equivalence(
    mcp_driver_python,
    calcpy_e2e_root: Path,
    python_bin: str,
    wall_clock_record,
) -> None:
    del wall_clock_record
    src = calcpy_e2e_root / "calcpy" / "calcpy.py"
    pre_rc, pre_pass, pre_fail = _run_pytest_doctest(calcpy_e2e_root, python_bin)
    assert pre_rc == 0
    assert pre_pass >= 4 and pre_fail == 0

    split_json = mcp_driver_python.split_file(
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
    split = json.loads(split_json)
    # v0.2.0 followup-I4 (strip-the-skip per L05): demand applied=True
    # unconditionally; the prior skip masked Stage 2B regressions.
    assert split.get("applied") is True, (
        f"E9-py split must apply deterministically; full payload={split!r}"
    )

    post_rc, post_pass, post_fail = _run_pytest_doctest(calcpy_e2e_root, python_bin)
    assert post_rc == 0
    assert (post_pass, post_fail) == (pre_pass, pre_fail), (
        f"semantic drift on calcpy: pre=({pre_pass},{pre_fail}) "
        f"post=({post_pass},{post_fail})"
    )
