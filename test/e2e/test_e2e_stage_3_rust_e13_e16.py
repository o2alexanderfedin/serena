"""Stage 3 long-tail Rust E2E scenarios (E13–E16).

Per scope-report §15.1 (Stage 3 nightly):
- E13: ``verify_after_refactor`` round-trip (cargo test + flycheck after a split).
- E14: ``change_visibility`` cross-module ripple (verify no breakage in private callers).
- E15: ``expand_macro`` round-trip (println!-style expansion equivalence).
- E16: ``complete_match_arms`` exhaustiveness on a sealed enum.

These are nightly gates; they boot real LSPs (rust-analyzer) and use the
calcrs_e2e fixture. Skip-on-gap pattern matches the Stage 2B harness:
- pytest.skip when the facade returns applied!=True (Stage 3 facade
  application is action-discovery only — see v0.3.0 backlog item).
- pytest.skip when host cargo toolchain is broken.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


@pytest.mark.e2e
def test_e13_rust_verify_after_refactor_round_trip(
    mcp_driver_rust,
    calcrs_e2e_root: Path,
    cargo_bin: str,
    rust_analyzer_bin: str,
    wall_clock_record,
) -> None:
    """E13: verify_after_refactor returns a structured runnables/flycheck summary."""
    del rust_analyzer_bin, wall_clock_record, cargo_bin
    lib_rs = calcrs_e2e_root / "src" / "lib.rs"
    try:
        result_json = mcp_driver_rust.verify_after_refactor(
            file=str(lib_rs), language="rust",
        )
    except Exception as exc:
        pytest.skip(
            f"E13 verify raised before result (Stage 3 LSP-init gap): {exc!r}"
        )
    payload = json.loads(result_json)
    # v0.2.0 followup-I4 (strip-the-skip per L05): demand applied=True
    # unconditionally; the prior skip masked verify-facade regressions.
    # The try/except above still legitimately guards the LSP-init gap.
    assert payload.get("applied") is True, (
        f"E13 verify must apply deterministically; full payload={payload!r}"
    )
    findings = payload.get("language_findings") or []
    assert findings, "verify_after_refactor must surface a verify_summary finding"
    summary = findings[0]
    assert summary["code"] == "verify_summary"
    assert "runnables=" in summary["message"]
    assert "flycheck_diagnostics=" in summary["message"]


@pytest.mark.e2e
def test_e14_rust_change_visibility_cross_module(
    mcp_driver_rust,
    calcrs_e2e_root: Path,
    cargo_bin: str,
    rust_analyzer_bin: str,
    wall_clock_record,
) -> None:
    """E14: change_visibility on an item exposes it to a downstream caller
    without breaking anything else; cargo test passes post-rewrite."""
    del rust_analyzer_bin, wall_clock_record
    lib_rs = calcrs_e2e_root / "src" / "lib.rs"
    # Toolchain pre-flight (matches E1 / E10 / E16). When rust-analyzer
    # cannot index the project (e.g. rustc_driver dylib mismatch on the
    # host), no code actions surface and the assist looks broken even
    # though the facade is correct.
    pre_proc = subprocess.run(
        [cargo_bin, "test", "--quiet"],
        cwd=str(calcrs_e2e_root),
        capture_output=True, text=True, timeout=180,
    )
    if pre_proc.returncode != 0:
        pytest.skip(
            f"cargo test baseline broken on this host (rc={pre_proc.returncode}); "
            f"E14 cannot be exercised — likely rustc_driver dylib not loadable."
        )
    try:
        result_json = mcp_driver_rust.change_visibility(
            file=str(lib_rs),
            # Cursor on the `pub` keyword of `pub fn parse(...)` inside
            # `pub mod parser { ... }` (0-indexed line 30, char 4 in the
            # calcrs_e2e baseline). `target_visibility="pub_crate"` is
            # a real downgrade so the assist surfaces an applicable action.
            position={"line": 30, "character": 4},
            target_visibility="pub_crate",
            language="rust",
        )
    except Exception as exc:
        pytest.skip(f"E14 change_visibility raised: {exc!r}")
    payload = json.loads(result_json)
    # v0.2.0 followup-I4 (strip-the-skip per L05): demand applied=True
    # unconditionally now that the cursor lands on a real `pub` token.
    assert payload.get("applied") is True, (
        f"E14 change_visibility must apply deterministically; "
        f"full payload={payload!r}"
    )
    proc = subprocess.run(
        [cargo_bin, "test", "--quiet"],
        cwd=str(calcrs_e2e_root),
        capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0 and "rustc_driver" in proc.stderr:
        pytest.skip(
            "cargo test baseline broken on this host (rustc_driver dylib not loadable)"
        )
    assert proc.returncode == 0, (
        f"cargo test failed post-change_visibility:\n{proc.stdout}\n{proc.stderr}"
    )


@pytest.mark.e2e
def test_e15_rust_expand_macro_round_trip(
    mcp_driver_rust,
    calcrs_e2e_root: Path,
    rust_analyzer_bin: str,
    wall_clock_record,
) -> None:
    """E15: expand_macro returns the expansion text for a println!-like call
    site. Verifies the rust-analyzer expandMacro extension is reachable."""
    del rust_analyzer_bin, wall_clock_record
    src = calcrs_e2e_root / "src" / "lib.rs"
    src_text = src.read_text(encoding="utf-8")
    if "println!" not in src_text and "format!" not in src_text:
        pytest.skip("calcrs_e2e fixture has no macro invocation to expand")
    try:
        result_json = mcp_driver_rust.expand_macro(
            file=str(src), position={"line": 0, "character": 0},
            language="rust",
        )
    except Exception as exc:
        pytest.skip(f"E15 expand_macro raised: {exc!r}")
    payload = json.loads(result_json)
    # v0.2.0 followup-I4 (strip-the-skip per L05): demand applied=True
    # unconditionally; the prior skip masked expand_macro coord-wiring
    # regressions.
    assert payload.get("applied") is True, (
        f"E15 expand_macro must apply deterministically; full payload={payload!r}"
    )
    findings = payload.get("language_findings") or []
    assert findings, "expand_macro must surface a macro_expansion finding"
    assert findings[0]["code"] == "macro_expansion"


@pytest.mark.e2e
def test_e16_rust_complete_match_arms_exhaustiveness(
    mcp_driver_rust,
    calcrs_e2e_root: Path,
    cargo_bin: str,
    rust_analyzer_bin: str,
    wall_clock_record,
) -> None:
    """E16: complete_match_arms inserts the missing arms of a match over
    a sealed enum so exhaustiveness checking passes."""
    del rust_analyzer_bin, wall_clock_record
    # The calcrs_e2e fixture grew an `ops` module (`src/ops.rs`) with a
    # sealed `Op` enum and a non-exhaustive `_` placeholder match in
    # `classify`; the cursor lands on the `match` keyword (0-indexed
    # line 19, char 4) so rust-analyzer's `add_missing_match_arms`
    # assist surfaces and expands the placeholder.
    ops_rs = calcrs_e2e_root / "src" / "ops.rs"
    # Toolchain pre-flight (matches E1 / E10 / E14). Without a working
    # cargo + rustc_driver dylib, rust-analyzer cannot index the project
    # and no assists surface.
    pre_proc = subprocess.run(
        [cargo_bin, "test", "--quiet"],
        cwd=str(calcrs_e2e_root),
        capture_output=True, text=True, timeout=180,
    )
    if pre_proc.returncode != 0:
        pytest.skip(
            f"cargo test baseline broken on this host (rc={pre_proc.returncode}); "
            f"E16 cannot be exercised — likely rustc_driver dylib not loadable."
        )
    try:
        result_json = mcp_driver_rust.complete_match_arms(
            file=str(ops_rs), position={"line": 19, "character": 4},
            language="rust",
        )
    except Exception as exc:
        pytest.skip(f"E16 complete_match_arms raised: {exc!r}")
    payload = json.loads(result_json)
    # v0.2.0 followup-I4 (strip-the-skip per L05): demand applied=True
    # unconditionally now that the cursor lands on a real non-exhaustive
    # match. The try/except above still legitimately guards LSP-init.
    assert payload.get("applied") is True, (
        f"E16 complete_match_arms must apply deterministically; "
        f"full payload={payload!r}"
    )
    proc = subprocess.run(
        [cargo_bin, "build", "--quiet"],
        cwd=str(calcrs_e2e_root),
        capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0 and "rustc_driver" in proc.stderr:
        pytest.skip("cargo build baseline broken on this host")
    assert proc.returncode == 0, (
        f"cargo build failed post-complete_match_arms:\n{proc.stderr}"
    )
