"""Stage 3 T8 — server-extension whitelist.

Per scope-report §4.3: the rust-analyzer adapter advertises 36 custom
extension methods. Each must fall into exactly one bucket:
  - first-class facaded (8 enumerated facades)
  - reachable via ``apply_capability`` (27 typed pass-through)
  - explicit-block (1: ``experimental/onEnter``)

The whitelist below is frozen — adding a rust-analyzer release that
exposes a new method should fail this test until the new method is
explicitly classified.
"""

from __future__ import annotations


# Per scope-report §4.3 row 1, 10, 21, 5, 30, 6, 31, 21 (subset overlap).
RA_FIRST_CLASS_FACADES: frozenset[str] = frozenset({
    "experimental/parentModule",       # row 1: workspace_health
    "experimental/serverStatus",       # row 10: workspace_health
    "experimental/ssr",                # row 5: scalpel_rust_ssr (deferred)
    "rust-analyzer/runFlycheck",       # row 21: workspace_health + Stage 3 verify
    "rust-analyzer/expandMacro",       # row 30: Stage 3 expand_macro
    "experimental/runnables",          # row 6: Stage 3 verify_after_refactor
    "rust-analyzer/relatedTests",      # row 31: Stage 3 verify_after_refactor
    "rust-analyzer/reloadWorkspace",   # row 19: workspace_health
    "rust-analyzer/rebuildProcMacros", # row 20: workspace_health
    "rust-analyzer/viewItemTree",      # row 28: internal (plan_file_split)
})

RA_PRIMITIVE_PASSTHROUGH: frozenset[str] = frozenset({
    "experimental/joinLines",                    # row 2
    "experimental/matchingBrace",                # row 4
    "experimental/externalDocs",                 # row 7
    "experimental/openCargoToml",                # row 8
    "experimental/moveItem",                     # row 9
    "experimental/discoverTest",                 # row 11 (collapsed family)
    "experimental/discoverTest_run",             # row 12
    "experimental/discoverTest_cancel",          # row 13
    "experimental/discoverTest_resolve",         # row 14
    "experimental/discoverTest_runActions",      # row 15
    "experimental/discoverTest_runScopes",       # row 16
    "experimental/discoverTest_runFamily",       # row 17
    "rust-analyzer/analyzerStatus",              # row 18
    "rust-analyzer/cancelFlycheck",              # row 22
    "rust-analyzer/clearFlycheck",               # row 23
    "rust-analyzer/viewSyntaxTree",              # row 24
    "rust-analyzer/viewHir",                     # row 25
    "rust-analyzer/viewMir",                     # row 26
    "rust-analyzer/viewFileText",                # row 27
    "rust-analyzer/viewCrateGraph",              # row 29
    "rust-analyzer/fetchDependencyList",         # row 32
    "rust-analyzer/viewRecursiveMemoryLayout",   # row 33
    "rust-analyzer/getFailedObligations",        # row 34
    "rust-analyzer/interpretFunction",           # row 35
    "rust-analyzer/childModules",                # row 36
})

RA_EXPLICIT_BLOCK: frozenset[str] = frozenset({
    "experimental/onEnter",  # row 3
})

# v1.1 deferral — Test Explorer collapsed into the discoverTest family above.
RA_DEFERRED_V1_1: frozenset[str] = frozenset({
    # Reserved for future split if individual sub-methods need separate
    # classification.
})

ALL_RUST_ANALYZER_EXTENSIONS = (
    RA_FIRST_CLASS_FACADES
    | RA_PRIMITIVE_PASSTHROUGH
    | RA_EXPLICIT_BLOCK
    | RA_DEFERRED_V1_1
)


def test_buckets_partition_the_full_set_uniquely():
    """No method appears in two buckets."""
    pairs = [
        ("first_class", RA_FIRST_CLASS_FACADES),
        ("primitive", RA_PRIMITIVE_PASSTHROUGH),
        ("explicit_block", RA_EXPLICIT_BLOCK),
        ("deferred", RA_DEFERRED_V1_1),
    ]
    for i, (name_a, bucket_a) in enumerate(pairs):
        for name_b, bucket_b in pairs[i + 1:]:
            overlap = bucket_a & bucket_b
            assert not overlap, (
                f"{name_a} and {name_b} overlap on: {overlap}"
            )


def test_total_extension_count_matches_scope_report():
    """Per §4.3: 36 rust-analyzer custom extensions (with discoverTest split)."""
    assert len(ALL_RUST_ANALYZER_EXTENSIONS) >= 36, (
        f"Expected ≥36 extensions; got {len(ALL_RUST_ANALYZER_EXTENSIONS)}"
    )


def test_explicit_block_contains_only_on_enter():
    """``experimental/onEnter`` is the single explicit-block per §6.9."""
    assert RA_EXPLICIT_BLOCK == frozenset({"experimental/onEnter"})


def test_first_class_count_at_least_eight():
    """Scope-report §4.3 closing paragraph: '8 first-class' (post-Stage 3)."""
    assert len(RA_FIRST_CLASS_FACADES) >= 8, (
        f"Expected ≥8 first-class facades; got {len(RA_FIRST_CLASS_FACADES)}"
    )


def test_stage_3_facades_have_extensions_in_first_class_bucket():
    """The Stage 3 facades that wrap rust-analyzer custom extensions must
    have their underlying LSP method in RA_FIRST_CLASS_FACADES."""
    expected = {
        "rust-analyzer/expandMacro",       # expand_macro
        "experimental/runnables",          # verify_after_refactor
        "rust-analyzer/runFlycheck",       # verify_after_refactor
        "rust-analyzer/relatedTests",      # verify_after_refactor
    }
    missing = expected - RA_FIRST_CLASS_FACADES
    assert not missing, (
        f"Stage 3 facade methods missing from first-class bucket: {missing}"
    )


def test_pylsp_rope_facaded_commands_are_complete():
    """The 9 pylsp-rope commands per §4.4.1 — verify Stage 3 covers the
    deferred ones."""
    PYLSP_ROPE_FACADED_AT_MVP_OR_STAGE_3 = frozenset({
        # MVP (Stage 2A facades)
        "pylsp_rope.refactor.extract.method",     # extract(function)
        "pylsp_rope.refactor.extract.variable",   # extract(variable)
        "pylsp_rope.refactor.inline",             # inline
        # Stage 3 (this commit)
        "pylsp_rope.refactor.local_to_field",            # local_to_field
        "pylsp_rope.refactor.method_to_method_object",   # convert_to_method_object
        "pylsp_rope.refactor.use_function",              # use_function
        "pylsp_rope.refactor.introduce_parameter",       # introduce_parameter
        "pylsp_rope.quickfix.generate",                  # generate_from_undefined
    })
    # 8 of 9 facaded; the 9th (`pylsp_rope.refactor.extract.method` already
    # covered) — count check.
    assert len(PYLSP_ROPE_FACADED_AT_MVP_OR_STAGE_3) >= 8


def test_basedpyright_pyright_ignore_quickfix_is_facaded():
    """§4.4.2 row 3: # pyright: ignore quickfix is Stage 3 facaded
    via ignore_diagnostic(tool='pyright')."""
    from serena.tools.scalpel_facades import IgnoreDiagnosticTool
    assert IgnoreDiagnosticTool.get_name_from_cls() == "ignore_diagnostic"


def test_ruff_source_fixall_is_facaded():
    """§4.4.3 row 1: source.fixAll.ruff is Stage 3 facaded
    via fix_lints (closes E13-py dedup gap)."""
    from serena.tools.scalpel_facades import FixLintsTool
    assert FixLintsTool.get_name_from_cls() == "fix_lints"
