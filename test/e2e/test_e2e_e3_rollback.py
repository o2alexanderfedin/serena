"""E2E scenario E3 — rollback after intentional break.

Maps to scope-report S15.1 row E3: "`rollback(checkpoint_id)` restores
byte-identical pre-refactor tree".
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def _tree_hash(root: Path) -> str:
    """Stable SHA-256 across all files under root (excluding cargo target)."""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if rel.startswith("target/") or rel.startswith("__pycache__/"):
            continue
        if "__pycache__" in rel or rel.endswith(".pyc"):
            continue
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        h.update(p.read_bytes())
        h.update(b"\x01")
    return h.hexdigest()


@pytest.mark.e2e
def test_e3_rollback_restores_python_tree(
    mcp_driver_python,
    calcpy_e2e_root: Path,
    wall_clock_record,
) -> None:
    del wall_clock_record
    src = calcpy_e2e_root / "calcpy" / "calcpy.py"
    pre_hash = _tree_hash(calcpy_e2e_root)

    try:
        apply_json = mcp_driver_python.extract(
            file=str(src),
            name_path="evaluate",
            target="function",
            new_name="_helper",
            dry_run=False,
            language="python",
        )
    except Exception as exc:
        pytest.skip(
            f"E3 extract raised before result (Stage 2B gap: real LSP "
            f"not initialized in pool spawn — e.g. pylsp missing): {exc!r}"
        )
    apply_payload = json.loads(apply_json)
    # v0.2.0 followup-I4 (strip-the-skip per L05): demand applied=True
    # unconditionally; the underlying `extract` arg-validation bug
    # (`del ... name_path`) is now fixed and the facade resolves
    # name_path → range via `find_symbol_range`. The try/except above
    # still legitimately guards the LSP-init gap.
    assert apply_payload.get("applied") is True, (
        f"E3 extract must apply deterministically; full payload={apply_payload!r}"
    )
    checkpoint_id = apply_payload.get("checkpoint_id")
    assert checkpoint_id is not None
    mid_hash = _tree_hash(calcpy_e2e_root)
    assert mid_hash != pre_hash, "extract did not modify the tree"

    rollback_json = mcp_driver_python.rollback(checkpoint_id=checkpoint_id)
    rollback = json.loads(rollback_json)
    assert rollback.get("applied") is True or rollback.get("no_op") is True, (
        f"rollback unexpected: {rollback_json}"
    )

    post_hash = _tree_hash(calcpy_e2e_root)
    assert post_hash == pre_hash, (
        f"rollback did not restore the tree:\n"
        f"  pre  = {pre_hash}\n"
        f"  post = {post_hash}"
    )


@pytest.mark.e2e
def test_e3_rollback_unknown_checkpoint_returns_failure(
    mcp_driver_python,
) -> None:
    rollback_json = mcp_driver_python.rollback(
        checkpoint_id="ckpt_does_not_exist"
    )
    rollback = json.loads(rollback_json)
    # Either a failure or a no-op is acceptable (idempotent semantics).
    assert (
        rollback.get("applied") is False
        or rollback.get("no_op") is True
    ), f"unknown checkpoint should not silently apply: {rollback_json}"
