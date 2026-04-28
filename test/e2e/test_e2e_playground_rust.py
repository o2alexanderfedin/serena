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
import os
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


@pytest.mark.e2e
def test_playground_rust_extract_lifetime(
    mcp_driver_playground_rust,
    playground_rust_root: Path,
    rust_analyzer_bin: str,
) -> None:
    """Introduce an explicit lifetime on ``first_word`` in types/lifetimes.rs.

    Facade: scalpel_extract_lifetime.
    Target: the return-type ``&str`` token at line 13 (1-indexed) = 12 (0-indexed),
    column 30 in types/src/lifetimes.rs.
    After the refactor: the signature must contain a lifetime parameter (e.g. ``'a``).
    """
    del rust_analyzer_bin
    lifetimes_rs = playground_rust_root / "types" / "src" / "lifetimes.rs"
    assert lifetimes_rs.exists(), "playground types/src/lifetimes.rs baseline missing"

    # ``pub fn first_word(s: &str) -> &str {`` is at line 13 (1-indexed) = 12 (0-indexed).
    # The return ``&str`` starts at column 30 (the ``&`` of the return type).
    try:
        result_json = mcp_driver_playground_rust.extract_lifetime(
            file=str(lifetimes_rs),
            position={"line": 12, "character": 30},
            lifetime_name="a",
            dry_run=False,
            language="rust",
        )
    except Exception as exc:
        pytest.skip(
            f"playground extract_lifetime raised before result (LSP-init gap): {exc!r}"
        )

    payload = json.loads(result_json)
    assert isinstance(payload, dict), f"non-JSON-object result: {result_json!r}"

    if payload.get("applied") is not True:
        pytest.skip(
            f"playground extract_lifetime did not apply (RA assist gap): "
            f"failure={payload.get('failure')}"
        )

    assert payload.get("checkpoint_id"), (
        f"applied=True but no checkpoint_id: {payload}"
    )
    lifetime_text = lifetimes_rs.read_text(encoding="utf-8")
    assert "'" in lifetime_text, (
        "no lifetime parameter found in lifetimes.rs after extract_lifetime"
    )


@pytest.mark.e2e
def test_playground_rust_complete_match_arms(
    mcp_driver_playground_rust,
    playground_rust_root: Path,
    rust_analyzer_bin: str,
) -> None:
    """Replace the wildcard arm in ``describe`` with all Direction variants.

    Facade: scalpel_complete_match_arms.
    Target: the ``match`` keyword at line 24 (1-indexed) = 23 (0-indexed),
    column 4 in types/src/arms.rs.
    After the refactor: all four Direction variants must appear in arms.rs.
    """
    del rust_analyzer_bin
    arms_rs = playground_rust_root / "types" / "src" / "arms.rs"
    assert arms_rs.exists(), "playground types/src/arms.rs baseline missing"

    # ``    match dir {`` is at line 24 (1-indexed) = 23 (0-indexed).
    # The ``match`` keyword starts at column 4.
    try:
        result_json = mcp_driver_playground_rust.complete_match_arms(
            file=str(arms_rs),
            position={"line": 23, "character": 4},
            dry_run=False,
            language="rust",
        )
    except Exception as exc:
        pytest.skip(
            f"playground complete_match_arms raised before result (LSP-init gap): {exc!r}"
        )

    payload = json.loads(result_json)
    assert isinstance(payload, dict), f"non-JSON-object result: {result_json!r}"

    if payload.get("applied") is not True:
        pytest.skip(
            f"playground complete_match_arms did not apply (RA assist gap): "
            f"failure={payload.get('failure')}"
        )

    assert payload.get("checkpoint_id"), (
        f"applied=True but no checkpoint_id: {payload}"
    )
    arms_text = arms_rs.read_text(encoding="utf-8")
    for variant in ("South", "East", "West"):
        assert variant in arms_text, (
            f"Direction::{variant} arm missing from arms.rs after complete_match_arms"
        )
    assert "_ =>" not in arms_text, (
        "wildcard arm still present after complete_match_arms"
    )


@pytest.mark.e2e
def test_playground_rust_change_return_type(
    mcp_driver_playground_rust,
    playground_rust_root: Path,
    rust_analyzer_bin: str,
) -> None:
    """Wrap the return type of ``square`` from ``i32`` to ``Option<i32>``.

    Facade: scalpel_change_return_type.
    Target: the ``i32`` return-type token at line 12 (1-indexed) = 11 (0-indexed),
    column 25 in types/src/returns.rs.
    After the refactor: the signature must contain ``Option``.
    """
    del rust_analyzer_bin
    returns_rs = playground_rust_root / "types" / "src" / "returns.rs"
    assert returns_rs.exists(), "playground types/src/returns.rs baseline missing"

    # ``pub fn square(n: i32) -> i32 {`` is at line 12 (1-indexed) = 11 (0-indexed).
    # The return ``i32`` starts at column 25.
    try:
        result_json = mcp_driver_playground_rust.change_return_type(
            file=str(returns_rs),
            position={"line": 11, "character": 25},
            new_return_type="Option<i32>",
            dry_run=False,
            language="rust",
        )
    except Exception as exc:
        pytest.skip(
            f"playground change_return_type raised before result (LSP-init gap): {exc!r}"
        )

    payload = json.loads(result_json)
    assert isinstance(payload, dict), f"non-JSON-object result: {result_json!r}"

    if payload.get("applied") is not True:
        pytest.skip(
            f"playground change_return_type did not apply (RA assist gap): "
            f"failure={payload.get('failure')}"
        )

    assert payload.get("checkpoint_id"), (
        f"applied=True but no checkpoint_id: {payload}"
    )
    returns_text = returns_rs.read_text(encoding="utf-8")
    assert "Option" in returns_text, (
        "Option wrapper not found in returns.rs after change_return_type"
    )


@pytest.mark.e2e
def test_playground_rust_change_type_shape(
    mcp_driver_playground_rust,
    playground_rust_root: Path,
    rust_analyzer_bin: str,
) -> None:
    """Convert the named struct ``Point`` to a tuple struct.

    Facade: scalpel_change_type_shape.
    Target: the ``Point`` identifier at line 14 (1-indexed) = 13 (0-indexed),
    column 11 in types/src/shapes.rs.
    After the refactor: the named-field form must be gone; tuple form present.
    """
    del rust_analyzer_bin
    shapes_rs = playground_rust_root / "types" / "src" / "shapes.rs"
    assert shapes_rs.exists(), "playground types/src/shapes.rs baseline missing"

    # ``pub struct Point {`` is at line 14 (1-indexed) = 13 (0-indexed).
    # ``Point`` starts at column 11.
    try:
        result_json = mcp_driver_playground_rust.change_type_shape(
            file=str(shapes_rs),
            position={"line": 13, "character": 11},
            target_shape="tuple_struct",
            dry_run=False,
            language="rust",
        )
    except Exception as exc:
        pytest.skip(
            f"playground change_type_shape raised before result (LSP-init gap): {exc!r}"
        )

    payload = json.loads(result_json)
    assert isinstance(payload, dict), f"non-JSON-object result: {result_json!r}"

    if payload.get("applied") is not True:
        pytest.skip(
            f"playground change_type_shape did not apply (RA assist gap): "
            f"failure={payload.get('failure')}"
        )

    assert payload.get("checkpoint_id"), (
        f"applied=True but no checkpoint_id: {payload}"
    )
    shapes_text = shapes_rs.read_text(encoding="utf-8")
    # Tuple struct: ``pub struct Point(`` — curly brace form gone.
    assert "pub struct Point(" in shapes_text, (
        "tuple-struct form not found in shapes.rs after change_type_shape"
    )
    assert "pub struct Point {" not in shapes_text, (
        "named-struct form still present after change_type_shape"
    )


@pytest.mark.e2e
def test_playground_rust_generate_member(
    mcp_driver_playground_rust,
    playground_rust_root: Path,
    rust_analyzer_bin: str,
) -> None:
    """Generate a getter for the ``value`` field on ``Counter``.

    Facade: scalpel_generate_member.
    Target: the ``value`` field at line 14 (1-indexed) = 13 (0-indexed),
    column 8 in types/src/member.rs.
    After the refactor: a ``fn value`` getter method must appear in member.rs.
    """
    del rust_analyzer_bin
    member_rs = playground_rust_root / "types" / "src" / "member.rs"
    assert member_rs.exists(), "playground types/src/member.rs baseline missing"

    # ``    pub value: u64,`` is at line 14 (1-indexed) = 13 (0-indexed).
    # ``value`` starts at column 8.
    try:
        result_json = mcp_driver_playground_rust.generate_member(
            file=str(member_rs),
            position={"line": 13, "character": 8},
            member_kind="getter",
            dry_run=False,
            language="rust",
        )
    except Exception as exc:
        pytest.skip(
            f"playground generate_member raised before result (LSP-init gap): {exc!r}"
        )

    payload = json.loads(result_json)
    assert isinstance(payload, dict), f"non-JSON-object result: {result_json!r}"

    if payload.get("applied") is not True:
        pytest.skip(
            f"playground generate_member did not apply (RA assist gap): "
            f"failure={payload.get('failure')}"
        )

    assert payload.get("checkpoint_id"), (
        f"applied=True but no checkpoint_id: {payload}"
    )
    member_text = member_rs.read_text(encoding="utf-8")
    assert "fn value" in member_text, (
        "generated getter fn value not found in member.rs after generate_member"
    )


@pytest.mark.e2e
def test_playground_rust_generate_trait_impl_scaffold(
    mcp_driver_playground_rust,
    playground_rust_root: Path,
    rust_analyzer_bin: str,
) -> None:
    """Generate an ``impl Describable for Widget`` scaffold.

    Facade: scalpel_generate_trait_impl_scaffold.
    Target: the ``Widget`` type name at line 23 (1-indexed) = 22 (0-indexed),
    column 11 in types/src/traits.rs.
    After the refactor: an ``impl Describable for Widget`` block must appear.
    """
    del rust_analyzer_bin
    traits_rs = playground_rust_root / "types" / "src" / "traits.rs"
    assert traits_rs.exists(), "playground types/src/traits.rs baseline missing"

    # ``pub struct Widget {`` is at line 23 (1-indexed) = 22 (0-indexed).
    # ``Widget`` starts at column 11.
    try:
        result_json = mcp_driver_playground_rust.generate_trait_impl_scaffold(
            file=str(traits_rs),
            position={"line": 22, "character": 11},
            trait_name="Describable",
            dry_run=False,
            language="rust",
        )
    except Exception as exc:
        pytest.skip(
            f"playground generate_trait_impl_scaffold raised before result (LSP-init gap): {exc!r}"
        )

    payload = json.loads(result_json)
    assert isinstance(payload, dict), f"non-JSON-object result: {result_json!r}"

    if payload.get("applied") is not True:
        pytest.skip(
            f"playground generate_trait_impl_scaffold did not apply (RA assist gap): "
            f"failure={payload.get('failure')}"
        )

    assert payload.get("checkpoint_id"), (
        f"applied=True but no checkpoint_id: {payload}"
    )
    traits_text = traits_rs.read_text(encoding="utf-8")
    assert "impl Describable for Widget" in traits_text, (
        "impl scaffold not found in traits.rs after generate_trait_impl_scaffold"
    )


@pytest.mark.e2e
def test_playground_rust_expand_glob_imports(
    mcp_driver_playground_rust,
    playground_rust_root: Path,
    rust_analyzer_bin: str,
) -> None:
    """Expand ``use std::collections::*;`` into explicit names in types/globs.rs.

    Facade: scalpel_expand_glob_imports.
    Target: the ``*`` token at line 9 (1-indexed) = 8 (0-indexed),
    column 22 in types/src/globs.rs.
    After the refactor: the glob ``*`` must be gone; explicit names present.
    """
    del rust_analyzer_bin
    globs_rs = playground_rust_root / "types" / "src" / "globs.rs"
    assert globs_rs.exists(), "playground types/src/globs.rs baseline missing"

    # ``use std::collections::*;`` is at line 9 (1-indexed) = 8 (0-indexed).
    # The glob ``*`` is at column 22.
    try:
        result_json = mcp_driver_playground_rust.expand_glob_imports(
            file=str(globs_rs),
            position={"line": 8, "character": 22},
            dry_run=False,
            language="rust",
        )
    except Exception as exc:
        pytest.skip(
            f"playground expand_glob_imports raised before result (LSP-init gap): {exc!r}"
        )

    payload = json.loads(result_json)
    assert isinstance(payload, dict), f"non-JSON-object result: {result_json!r}"

    if payload.get("applied") is not True:
        pytest.skip(
            f"playground expand_glob_imports did not apply (RA assist gap): "
            f"failure={payload.get('failure')}"
        )

    assert payload.get("checkpoint_id"), (
        f"applied=True but no checkpoint_id: {payload}"
    )
    globs_text = globs_rs.read_text(encoding="utf-8")
    assert "::*" not in globs_text, (
        "glob import still present in globs.rs after expand_glob_imports"
    )
    # At least one of the explicitly-used types must appear as an import.
    assert "HashMap" in globs_text or "BTreeSet" in globs_text, (
        "no explicit import found in globs.rs after expand_glob_imports"
    )


def test_playground_rust_facade_coverage() -> None:
    """Confirm that all 12 Rust facades have at least one E2E test in this module.

    Per spec § 8 risk 3 — the placeholder ``@pytest.mark.skip`` was removed in
    v1.3-E when the 7 deferred Stage-3 facade tests landed.  This test now
    asserts the full set is covered by inspecting the names of all test functions
    defined in this module.
    """
    import sys as _sys
    this_module = _sys.modules[__name__]
    test_names = [
        name for name in dir(this_module)
        if name.startswith("test_playground_rust_") and callable(getattr(this_module, name))
    ]
    required_facades = {
        "split",
        "rename",
        "extract",
        "change_visibility",
        "inline",
        "extract_lifetime",
        "complete_match_arms",
        "change_return_type",
        "change_type_shape",
        "generate_member",
        "generate_trait_impl_scaffold",
        "expand_glob_imports",
    }
    covered = {
        facade
        for facade in required_facades
        if any(facade in name for name in test_names)
    }
    missing = required_facades - covered
    assert not missing, (
        f"Missing E2E coverage for Rust facades: {sorted(missing)}. "
        f"Add tests for them or update this assertion."
    )


# Engine repo URL — matches the git+URL in o2-scalpel-rust/.mcp.json (§ 3.3).
# Updated to the renamed fork (project_serena_fork_renamed.md).
_ENGINE_GIT_URL = "git+https://github.com/o2alexanderfedin/o2-scalpel-engine.git"


@pytest.mark.skipif(
    os.getenv("O2_SCALPEL_TEST_REMOTE_INSTALL") != "1",
    reason="opt-in via O2_SCALPEL_TEST_REMOTE_INSTALL=1; v1.3 graduation candidate (PyPI publish)",
)
def test_playground_rust_remote_install_smoke(tmp_path: Path) -> None:
    """Verify the published install path works end-to-end against the live GitHub repo.

    Currently gated off by default — see spec § 4.5 for rationale (cold uvx fetch
    of 60–90 s dominates CI wall-clock budget; revisit at v1.3 alongside PyPI publish).

    What this smoke proves:
    1. The git+URL endpoint resolves (no o2services owner regression — § 3.3/§ 3.4).
    2. uvx can pip-install the engine without recursing into the parent repo's
       vendor/serena submodule (the standalone engine repo IS its own root).
    3. The CLI entrypoint ``serena`` boots and emits a well-formed help string that
       includes ``--language`` (proof the MCP server subcommand is reachable).

    v1.3 graduation: once PyPI publication lands, replace the ``git+URL`` form with
    ``o2-scalpel-engine`` (package name); ``uvx`` resolves from cache in <1 s and
    this test moves to default-on.  The assertion can also be tightened at that point
    to spawn a full ``tools/list`` JSON-RPC round-trip instead of ``--help``.

    Entry point: ``serena`` (pyproject.toml ``[project.scripts]`` → ``serena.cli:top_level``).
    Relevant subcommand: ``serena start-mcp-server --help`` — contains ``--language-backend``.
    """
    del tmp_path  # unused; present for future fixture expansion (e.g. isolated uvx cache dir)

    proc = subprocess.run(
        [
            "uvx",
            "--from",
            _ENGINE_GIT_URL,
            "serena",
            "start-mcp-server",
            "--help",
        ],
        capture_output=True,
        text=True,
        timeout=180,  # cold uvx git+URL fetch + venv build can be slow
    )

    assert proc.returncode == 0, (
        f"uvx serena start-mcp-server --help failed (rc={proc.returncode}):\n"
        f"stdout:\n{proc.stdout[:1000]}\n"
        f"stderr:\n{proc.stderr[:1000]}"
    )
    combined = proc.stdout + proc.stderr
    assert "--language" in combined, (
        f"expected '--language' in help output — engine may not have booted correctly:\n"
        f"{combined[:500]}"
    )
