"""P-WB - workspace-boundary rule on calcrs seed (Q4).

Validates ``is_in_workspace(target, roots)``: resolves both sides to absolute
canonical paths, returns True iff target equals a root or has root + os.sep
as a prefix. Pure Python; no LSP boot. ``Path.resolve()`` (non-strict) returns
canonical form even for non-existent paths on macOS/Linux.
"""

from __future__ import annotations

import os
from pathlib import Path

from .conftest import write_spike_result


def is_in_workspace(target: Path, roots: list[Path]) -> bool:
    t = target.resolve()
    for root in roots:
        r = root.resolve()
        if t == r or str(t).startswith(str(r) + os.sep):
            return True
    return False


def test_p_wb_workspace_boundary(seed_rust_root: Path, results_dir: Path, tmp_path: Path) -> None:
    root = seed_rust_root.resolve()
    extra = tmp_path / "extra_workspace"
    extra.mkdir()
    inside_extra = extra / "extra_file.rs"
    inside_extra.write_text("// in extra workspace", encoding="utf-8")

    cases = [
        ("inside main workspace", root / "src" / "lib.rs", [root], True),
        ("outside (registry)", Path.home() / ".cargo" / "registry" / "src" / "fake-0.0.0" / "lib.rs", [root], False),
        ("outside (random tmp)", tmp_path / "outside.rs", [root], False),
        ("extra_paths included", inside_extra, [root, extra], True),
        ("extra_paths NOT included", inside_extra, [root], False),
    ]

    results = []
    for lbl, p, rs, exp in cases:
        obs = is_in_workspace(p, rs)
        results.append({"case": lbl, "expected": exp, "observed": obs, "match": obs == exp})
    failures = [r for r in results if not r["match"]]
    rows = "\n".join(
        f"| {r['case']} | {r['expected']} | {r['observed']} | {'OK' if r['match'] else 'FAIL'} |" for r in results
    )
    body = f"""# P-WB - workspace-boundary rule on calcrs seed

**Outcome:** {len(results) - len(failures)}/{len(results)} cases match expected.

## Cases

| Case | Expected | Observed | Result |
|---|---|---|---|
{rows}

## Failures

{len(failures)} failing case(s): `{failures!r}`

## Decision

- 0 failures -> adopt `is_in_workspace(target, roots)` verbatim in the
  Stage 1A `WorkspaceEditApplier` per Q4 §7.1. The `OutsideWorkspace`
  annotation is advisory; the path filter is enforcement.
- >0 failures -> tighten canonicalization (`os.path.realpath` + symlink
  audit) and revisit on Windows (case-insensitive drives, UNC, 8.3 names).

`extra_paths` proves `O2_SCALPEL_WORKSPACE_EXTRA_PATHS` plumbing works:
vendored crates outside LSP-reported workspace folders can be allow-listed
without weakening the boundary for unrelated paths.
"""
    write_spike_result(results_dir, "P-WB", body)
    assert not failures, f"workspace-boundary classifier failed on {len(failures)} case(s): {failures!r}"
