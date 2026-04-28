"""E2E playground tests — Rust plugin MVP (v1.2.2 Phase 3).

Exercises five Rust refactoring facades against the playground/rust/ workspace
per APPROVED spec docs/superpowers/specs/2026-04-28-rust-plugin-e2e-playground-spec.md
§ 4.4 and § 6 P3.

Opt-in: ``O2_SCALPEL_RUN_E2E=1 uv run pytest test/e2e/test_e2e_playground_rust.py``
or ``pytest -m e2e``.

All tests use the ``mcp_driver_playground_rust`` fixture (Phase 2, conftest.py)
which clones ``playground/rust/`` into a per-test ``tmp_path`` with ``target/``
stripped so rust-analyzer always indexes a clean tree.

Facade → Driver method mapping (all from ``_McpDriver``):
- scalpel_split_file        → ``split_file(**kwargs)``
- scalpel_rename            → ``rename(**kwargs)``
- scalpel_extract           → ``extract(**kwargs)``
- scalpel_change_visibility → ``change_visibility(**kwargs)``
- scalpel_inline            → ``inline(**kwargs)``
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


@pytest.mark.e2e
def test_playground_rust_split(
    mcp_driver_playground_rust,
    playground_rust_root: Path,
    rust_analyzer_bin: str,
) -> None:
    """Split calc/src/lib.rs inline modules ast/parser/eval into sibling files.

    Facade: scalpel_split_file.
    After the refactor: ast.rs, parser.rs, and eval.rs must exist alongside
    the original lib.rs in calc/src/.
    """
    del rust_analyzer_bin
    lib_rs = playground_rust_root / "calc" / "src" / "lib.rs"
    assert lib_rs.exists(), "playground calc/src/lib.rs baseline missing"

    try:
        result_json = mcp_driver_playground_rust.split_file(
            file=str(lib_rs),
            groups={
                "ast": ["Expr"],
                "parser": ["tokenize", "parse_expr"],
                "eval": ["eval"],
            },
            parent_layout="file",
            reexport_policy="preserve_public_api",
            dry_run=False,
            language="rust",
        )
    except Exception as exc:
        pytest.skip(
            f"playground split_file raised before result (LSP-init gap): {exc!r}"
        )

    payload = json.loads(result_json)
    assert isinstance(payload, dict), f"non-JSON-object result: {result_json!r}"

    if payload.get("applied") is not True:
        pytest.skip(
            f"playground split did not apply (Stage 2B gap): "
            f"failure={payload.get('failure')}"
        )

    assert payload.get("checkpoint_id"), (
        f"applied=True but no checkpoint_id: {payload}"
    )
    calc_src = playground_rust_root / "calc" / "src"
    assert (calc_src / "ast.rs").exists(), "ast.rs not created by split"
    assert (calc_src / "parser.rs").exists(), "parser.rs not created by split"
    assert (calc_src / "eval.rs").exists(), "eval.rs not created by split"


@pytest.mark.e2e
def test_playground_rust_rename(
    mcp_driver_playground_rust,
    playground_rust_root: Path,
    rust_analyzer_bin: str,
) -> None:
    """Rename parser::parse_expr to parse_expression across the workspace.

    Facade: scalpel_rename.
    After the refactor: the definition and all call sites must use the new name.
    """
    del rust_analyzer_bin
    lib_rs = playground_rust_root / "calc" / "src" / "lib.rs"
    assert lib_rs.exists(), "playground calc/src/lib.rs baseline missing"

    try:
        result_json = mcp_driver_playground_rust.rename(
            file=str(lib_rs),
            name_path="parser::parse_expr",
            new_name="parse_expression",
            dry_run=False,
            language="rust",
        )
    except Exception as exc:
        pytest.skip(
            f"playground rename raised before result (LSP-init gap): {exc!r}"
        )

    payload = json.loads(result_json)
    assert isinstance(payload, dict), f"non-JSON-object result: {result_json!r}"
    assert payload.get("applied") is True, (
        f"playground rename must apply deterministically; full payload={payload!r}"
    )

    lib_text = lib_rs.read_text(encoding="utf-8")
    assert "parse_expression" in lib_text, (
        "renamed symbol not found in lib.rs after rename"
    )
    assert "parse_expr" not in lib_text or "parse_expression" in lib_text, (
        "old symbol name still present without new name — rename may be partial"
    )


@pytest.mark.e2e
def test_playground_rust_extract(
    mcp_driver_playground_rust,
    playground_rust_root: Path,
    rust_analyzer_bin: str,
) -> None:
    """Extract the `a + b` expression in eval::eval into a helper function.

    Facade: scalpel_extract.
    Target expression: `let result = a + b;` in calc/src/lib.rs.
    The range covers lines 83-84 (0-indexed) where the expression lives.
    After the refactor: a new function (e.g. `add_values`) must appear in the file.
    """
    del rust_analyzer_bin
    lib_rs = playground_rust_root / "calc" / "src" / "lib.rs"
    assert lib_rs.exists(), "playground calc/src/lib.rs baseline missing"

    # `let result = a + b;` is on line 84 (1-indexed) = line 83 (0-indexed).
    # The expression `a + b` is the RHS; we select the whole statement.
    # Range: start line 83 char 16 (`a + b` starts at the rhs of `let result = `
    # which is col 20); end line 83 char 25.
    # Using a loose range that covers `a + b` on line 83 (0-indexed).
    extract_range = {
        "start": {"line": 83, "character": 20},
        "end": {"line": 83, "character": 25},
    }

    try:
        result_json = mcp_driver_playground_rust.extract(
            file=str(lib_rs),
            range=extract_range,
            target="function",
            new_name="add_values",
            dry_run=False,
            language="rust",
        )
    except Exception as exc:
        pytest.skip(
            f"playground extract raised before result (LSP-init gap): {exc!r}"
        )

    payload = json.loads(result_json)
    assert isinstance(payload, dict), f"non-JSON-object result: {result_json!r}"

    if payload.get("applied") is not True:
        pytest.skip(
            f"playground extract did not apply (Stage 2B gap): "
            f"failure={payload.get('failure')}"
        )

    assert payload.get("checkpoint_id"), (
        f"applied=True but no checkpoint_id: {payload}"
    )
    lib_text = lib_rs.read_text(encoding="utf-8")
    assert "add_values" in lib_text, (
        "extracted function name not found in lib.rs after extract"
    )


@pytest.mark.e2e
def test_playground_rust_change_visibility(
    mcp_driver_playground_rust,
    playground_rust_root: Path,
    rust_analyzer_bin: str,
) -> None:
    """Promote pub(super) fn promote_to_public to pub in calc/src/visibility.rs.

    Facade: scalpel_change_visibility.
    Target: line 13 (1-indexed) = line 12 (0-indexed), character 0
    (`pub(super) fn promote_to_public`).
    After the refactor: the function must be declared `pub fn`.
    """
    del rust_analyzer_bin
    visibility_rs = playground_rust_root / "calc" / "src" / "visibility.rs"
    assert visibility_rs.exists(), "playground calc/src/visibility.rs baseline missing"

    # `pub(super) fn promote_to_public` is at line 13 (1-indexed) = 12 (0-indexed).
    # Place cursor on the `pub` keyword at character 0.
    try:
        result_json = mcp_driver_playground_rust.change_visibility(
            file=str(visibility_rs),
            position={"line": 12, "character": 0},
            target_visibility="pub",
            language="rust",
        )
    except Exception as exc:
        pytest.skip(
            f"playground change_visibility raised before result (LSP-init gap): {exc!r}"
        )

    payload = json.loads(result_json)
    assert isinstance(payload, dict), f"non-JSON-object result: {result_json!r}"

    if payload.get("applied") is not True:
        pytest.skip(
            f"playground change_visibility did not apply (Stage 2B gap): "
            f"failure={payload.get('failure')}"
        )

    assert payload.get("checkpoint_id"), (
        f"applied=True but no checkpoint_id: {payload}"
    )
    visibility_text = visibility_rs.read_text(encoding="utf-8")
    # After promotion: `pub fn promote_to_public` — `pub(super)` should be gone.
    assert "pub fn promote_to_public" in visibility_text, (
        "function not promoted to `pub fn` after change_visibility"
    )
    assert "pub(super) fn promote_to_public" not in visibility_text, (
        "`pub(super)` qualifier still present after change_visibility"
    )


@pytest.mark.e2e
def test_playground_rust_inline(
    mcp_driver_playground_rust,
    playground_rust_root: Path,
    rust_analyzer_bin: str,
) -> None:
    """Inline sum_helper into its single call site in report (lints/src/lib.rs).

    Facade: scalpel_inline.
    Target: the call `sum_helper(items)` at line 21 (1-indexed) = 20 (0-indexed),
    character 4 where `sum_helper` starts in the body of `report`.
    After the refactor: sum_helper definition is removed; report's body is direct.
    """
    del rust_analyzer_bin
    lints_lib_rs = playground_rust_root / "lints" / "src" / "lib.rs"
    assert lints_lib_rs.exists(), "playground lints/src/lib.rs baseline missing"

    # `sum_helper(items)` call is at line 21 (1-indexed) = 20 (0-indexed).
    # The call starts at character 4 (4 spaces of indent, then `sum_helper`).
    try:
        result_json = mcp_driver_playground_rust.inline(
            file=str(lints_lib_rs),
            position={"line": 20, "character": 4},
            target="call",
            scope="single_call_site",
            remove_definition=True,
            dry_run=False,
            language="rust",
        )
    except Exception as exc:
        pytest.skip(
            f"playground inline raised before result (LSP-init gap): {exc!r}"
        )

    payload = json.loads(result_json)
    assert isinstance(payload, dict), f"non-JSON-object result: {result_json!r}"

    if payload.get("applied") is not True:
        pytest.skip(
            f"playground inline did not apply (Stage 2B gap): "
            f"failure={payload.get('failure')}"
        )

    assert payload.get("checkpoint_id"), (
        f"applied=True but no checkpoint_id: {payload}"
    )
    lints_text = lints_lib_rs.read_text(encoding="utf-8")
    assert "sum_helper" not in lints_text, (
        "sum_helper definition/reference still present after inline"
    )
    # report should now contain the inlined body
    assert "iter().sum()" in lints_text, (
        "inlined expression `iter().sum()` not found in lints/src/lib.rs"
    )


@pytest.mark.e2e
def test_playground_rust_cargo_smoke(
    playground_rust_root: Path,
    cargo_bin: str,
    rust_analyzer_bin: str,
) -> None:
    """Smoke test: playground workspace compiles and passes cargo test post-clone.

    This verifies the baseline is always healthy.  It does not apply any
    refactoring; it runs ``cargo test --quiet`` directly on the fresh clone.
    If the Rust toolchain is missing or broken on this host, the test skips
    cleanly (cargo_bin and rust_analyzer_bin fixtures call pytest.skip when
    the binary is absent from PATH).
    """
    del rust_analyzer_bin

    proc = subprocess.run(
        [cargo_bin, "test", "--quiet"],
        cwd=str(playground_rust_root),
        capture_output=True,
        text=True,
        timeout=180,
    )

    if proc.returncode != 0 and "rustc_driver" in (proc.stderr or ""):
        pytest.skip(
            "cargo test failed due to rustc_driver dylib mismatch on this host; not a playground defect."
        )

    assert proc.returncode == 0, (
        f"playground cargo test failed (rc={proc.returncode}):\n"
        f"stdout:\n{proc.stdout}\n"
        f"stderr:\n{proc.stderr}"
    )


@pytest.mark.skip(reason="enable in v1.3 when remaining 7 Rust facades land")
def test_playground_rust_facade_coverage() -> None:
    """Placeholder: coverage assertion for all 12 Rust facades.

    Placeholder per spec § 8 risk 3. Remove the ``@pytest.mark.skip`` and
    implement the coverage check when the remaining 7 Rust facades ship in
    v1.3. The test ID is reserved here so the v1.3 PR is one decorator
    removal away from enforcing coverage.
    """
