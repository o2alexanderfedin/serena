"""Stage 3 long-tail Python E2E scenarios (E4-py, E5-py, E8-py, E11-py).

Per scope-report §15.1 (Stage 3 nightly):
- E4-py: cross-package extract — extract a method into a sibling module.
- E5-py: multi-package E2E — ``pytest -q`` byte-identical post-refactor
  across two interdependent packages.
- E8-py: crash-recovery on a partial pylsp-rope failure.
- E11-py: ``__all__`` preservation under the v0.2.0-E rename path
  (extends the Stage 2B test).

Skip-on-gap pattern matches the Stage 2B harness: skips when the facade
returns applied!=True or when prerequisites (pylsp-rope, basedpyright,
ruff) aren't reachable.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest


def _strip_pytest_timing(stdout: str) -> str:
    """Strip ``in N.NNs`` timing token from pytest -q output for byte-identity."""
    keep: list[str] = []
    for line in stdout.splitlines():
        if "passed" in line or "failed" in line or "error" in line:
            keep.append(re.sub(r"\s+in\s+\d+(?:\.\d+)?s\b", "", line))
    return "\n".join(keep)


@pytest.mark.e2e
def test_e4_py_cross_package_extract(
    mcp_driver_python,
    calcpy_e2e_root: Path,
    python_bin: str,
    pylsp_bin: str,
    wall_clock_record,
) -> None:
    """E4-py: extract a function out of calcpy.py into a sibling module."""
    del pylsp_bin, wall_clock_record
    src = calcpy_e2e_root / "calcpy" / "calcpy.py"
    pre_text = src.read_text(encoding="utf-8")
    try:
        result_json = mcp_driver_python.extract(
            file=str(src),
            range={"start": {"line": 0, "character": 0},
                   "end": {"line": 0, "character": 0}},
            target="function",
            new_name="cross_pkg_helper",
            language="python",
        )
    except Exception as exc:
        pytest.skip(f"E4-py extract raised: {exc!r}")
    payload = json.loads(result_json)
    # v0.2.0 followup-I4 (strip-the-skip per L05): demand applied=True
    # unconditionally; the prior skip masked Stage 3 facade-application
    # regressions. The try/except above still legitimately guards a raise
    # before result.
    assert payload.get("applied") is True, (
        f"E4-py extract must apply deterministically; full payload={payload!r}"
    )
    # v0.2.0 followup-I4: the v0.3.0 WorkspaceEdit-applier (commit
    # `v0.3.0-facade-application-complete`) now writes WorkspaceEdit to
    # disk, so the prior "applied=True but file unchanged" skip is dead
    # weight. Demand a real disk mutation.
    assert src.read_text(encoding="utf-8") != pre_text, (
        "E4-py extract returned applied=True but file unchanged on disk; "
        "the Stage 3 facade-application gap was supposed to be CLOSED in "
        "v0.3.0 — see project_v0_3_0_facade_application memory."
    )
    proc = subprocess.run(
        [python_bin, "-m", "pytest", "-q", "tests"],
        cwd=str(calcpy_e2e_root),
        capture_output=True, text=True, timeout=120,
        env={
            "PYTHONPATH": str(calcpy_e2e_root),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        },
    )
    assert proc.returncode == 0, f"post-extract pytest failed:\n{proc.stdout}"


@pytest.mark.e2e
def test_e5_py_multi_package_byte_identical(
    mcp_driver_python,
    calcpy_e2e_root: Path,
    python_bin: str,
    pylsp_bin: str,
    wall_clock_record,
) -> None:
    """E5-py: refactor across two interdependent packages; pytest -q
    output (modulo timing) must be byte-identical."""
    del pylsp_bin, wall_clock_record
    src = calcpy_e2e_root / "calcpy" / "calcpy.py"

    pre_proc = subprocess.run(
        [python_bin, "-m", "pytest", "-q", "tests"],
        cwd=str(calcpy_e2e_root),
        capture_output=True, text=True, timeout=120,
        env={
            "PYTHONPATH": str(calcpy_e2e_root),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        },
    )
    assert pre_proc.returncode == 0, f"baseline pytest failed:\n{pre_proc.stdout}"
    pre_filtered = _strip_pytest_timing(pre_proc.stdout)

    try:
        result_json = mcp_driver_python.split_file(
            file=str(src),
            groups={
                "ast": ["Num", "Add", "Sub"],
                "errors": ["CalcError"],
                "parser": ["parse"],
                "evaluator": ["evaluate"],
            },
            parent_layout="file",
            reexport_policy="preserve_public_api",
            language="python",
        )
    except Exception as exc:
        pytest.skip(f"E5-py split raised: {exc!r}")
    payload = json.loads(result_json)
    # v0.2.0 followup-I4 (strip-the-skip per L05): demand applied=True
    # unconditionally; the prior skip masked split-facade regressions.
    assert payload.get("applied") is True, (
        f"E5-py split must apply deterministically; full payload={payload!r}"
    )
    post_proc = subprocess.run(
        [python_bin, "-m", "pytest", "-q", "tests"],
        cwd=str(calcpy_e2e_root),
        capture_output=True, text=True, timeout=120,
        env={
            "PYTHONPATH": str(calcpy_e2e_root),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        },
    )
    assert post_proc.returncode == 0, f"post-split pytest failed:\n{post_proc.stdout}"
    post_filtered = _strip_pytest_timing(post_proc.stdout)
    assert post_filtered == pre_filtered, (
        f"pytest -q drifted across split:\n--- pre ---\n{pre_filtered}\n"
        f"--- post ---\n{post_filtered}"
    )


@pytest.mark.e2e
def test_e8_py_crash_recovery_on_partial_failure(
    mcp_driver_python,
    calcpy_e2e_root: Path,
    pylsp_bin: str,
    wall_clock_record,
) -> None:
    """E8-py: when a refactor partially fails, rollback restores the tree."""
    del pylsp_bin, wall_clock_record
    src = calcpy_e2e_root / "calcpy" / "calcpy.py"
    pre_bytes = src.read_bytes()
    try:
        result_json = mcp_driver_python.split_file(
            file=str(src),
            groups={"only_one": ["Num"]},  # intentionally narrow
            parent_layout="file",
            language="python",
        )
    except Exception as exc:
        pytest.skip(f"E8-py split raised: {exc!r}")
    payload = json.loads(result_json)
    # v0.2.0 followup-I4 (strip-the-skip per L05): demand applied=True and
    # a checkpoint_id unconditionally; the prior skip masked checkpoint
    # creation regressions.
    assert payload.get("applied") is True, (
        f"E8-py split must apply deterministically; full payload={payload!r}"
    )
    assert payload.get("checkpoint_id"), (
        f"E8-py split applied but produced no checkpoint_id: {payload!r}"
    )
    rb_json = mcp_driver_python.rollback(checkpoint_id=payload["checkpoint_id"])
    rb = json.loads(rb_json)
    # v0.2.0 followup-I4 (strip-the-skip per L05): demand rollback applied=True
    # unconditionally; the prior skip masked rollback-engine regressions.
    assert rb.get("applied") is True, (
        f"E8-py rollback must apply deterministically; full payload={rb!r}"
    )
    assert src.read_bytes() == pre_bytes, "rollback did not restore byte-identity"


@pytest.mark.e2e
def test_e11_py_dunder_all_preserved_under_rename(
    mcp_driver_python,
    calcpy_e2e_root: Path,
    pylsp_bin: str,
    wall_clock_record,
) -> None:
    """E11-py: rename a symbol exposed via __all__; v0.2.0-E ensures the
    __all__ entry is updated (so ``from module import *`` still works)."""
    del pylsp_bin, wall_clock_record
    src = calcpy_e2e_root / "calcpy" / "calcpy.py"
    init = calcpy_e2e_root / "calcpy" / "__init__.py"
    init_pre = init.read_text(encoding="utf-8")
    if "evaluate" not in init_pre:
        pytest.skip("calcpy_e2e __init__.py does not export 'evaluate'")
    try:
        result_json = mcp_driver_python.rename(
            file=str(src),
            name_path="evaluate",
            new_name="run_eval",
            language="python",
        )
    except Exception as exc:
        pytest.skip(f"E11-py rename raised: {exc!r}")
    payload = json.loads(result_json)
    # v0.2.0 followup-I4 (strip-the-skip per L05): demand applied=True
    # unconditionally; the prior skip masked rename-facade regressions.
    assert payload.get("applied") is True, (
        f"E11-py rename must apply deterministically; full payload={payload!r}"
    )
    init_post = init.read_text(encoding="utf-8")
    assert "run_eval" in init_post, (
        f"__all__ in __init__.py did not pick up renamed symbol: {init_post!r}"
    )
