"""v1.9.3 Item D — facade inventory regression guard.

Pins the current Scalpel-tool count so a future inadvertent facade
addition trips a fast local test instead of slipping past code review.
The v2.0 ceiling target is 40 ergonomic facades (memory:
``project_v1_6_v1_7_stub_facade_fix``); each new facade past today's
inventory must satisfy the 3-user-request demand gate before it can be
admitted.

The roadmap of 4 candidate slots + gates is at
``docs/superpowers/specs/2026-04-29-v2-0-facade-ceiling-roadmap.md``.

This test enumerates ``Scalpel*Tool`` classes in
``serena.tools.scalpel_facades`` and ``serena.tools.scalpel_primitives``
and checks the canonical snake-case projection against an explicit
allow-list. New facades go through the allow-list (along with the
demand evidence) so the regression guard has a paper trail.
"""
from __future__ import annotations

import re

import pytest

from serena.tools import scalpel_facades, scalpel_primitives


def _classname_to_snake(name: str) -> str:
    stripped = name[: -len("Tool")] if name.endswith("Tool") else name
    return re.sub(r"(?<!^)(?=[A-Z])", "_", stripped).lower()


def _enumerate_tools() -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for module in (scalpel_facades, scalpel_primitives):
        for name in dir(module):
            if not name.startswith("Scalpel") or not name.endswith("Tool"):
                continue
            cls = getattr(module, name)
            if not isinstance(cls, type):
                continue
            snake = _classname_to_snake(name)
            if snake in seen:
                continue
            seen.add(snake)
            out.append(snake)
    out.sort()
    return out


# Allow-list as of v1.9.3 / Item D close. 46 entries = 34 ergonomic facades
# + 12 primitives/operators. To extend, append the new tool's snake_case
# name AND its 3-user-request demand evidence to the v2.0 roadmap doc
# referenced in the module docstring above.
EXPECTED_TOOLS = frozenset({
    "scalpel_annotate_return_type",
    "scalpel_apply_capability",
    "scalpel_auto_import_specialized",
    "scalpel_capabilities_list",
    "scalpel_capability_describe",
    "scalpel_change_return_type",
    "scalpel_change_type_shape",
    "scalpel_change_visibility",
    "scalpel_complete_match_arms",
    "scalpel_confirm_annotations",
    "scalpel_convert_from_relative_imports",
    "scalpel_convert_module_layout",
    "scalpel_convert_to_async",
    "scalpel_convert_to_method_object",
    "scalpel_dry_run_compose",
    "scalpel_execute_command",
    "scalpel_expand_glob_imports",
    "scalpel_expand_macro",
    "scalpel_extract",
    "scalpel_extract_lifetime",
    "scalpel_extract_section",
    "scalpel_fix_lints",
    "scalpel_generate_constructor",
    "scalpel_generate_from_undefined",
    "scalpel_generate_member",
    "scalpel_generate_trait_impl_scaffold",
    "scalpel_ignore_diagnostic",
    "scalpel_imports_organize",
    "scalpel_inline",
    "scalpel_install_lsp_servers",
    "scalpel_introduce_parameter",
    "scalpel_local_to_field",
    "scalpel_organize_links",
    "scalpel_override_methods",
    "scalpel_reload_plugins",
    "scalpel_rename",
    "scalpel_rename_heading",
    "scalpel_rollback",
    "scalpel_split_doc",
    "scalpel_split_file",
    "scalpel_tidy_structure",
    "scalpel_transaction_commit",
    "scalpel_transaction_rollback",
    "scalpel_use_function",
    "scalpel_verify_after_refactor",
    "scalpel_workspace_health",
})


def test_facade_inventory_matches_allowlist() -> None:
    """Pin the v1.9.3 inventory. Drift in either direction trips this test
    so an accidental facade addition (or removal) lands with explicit
    allow-list maintenance and a v2.0 roadmap update."""
    actual = set(_enumerate_tools())
    extra = actual - EXPECTED_TOOLS
    missing = EXPECTED_TOOLS - actual
    assert not extra, (
        f"new facade(s) added without allow-list update: {sorted(extra)}; "
        "see docs/superpowers/specs/2026-04-29-v2-0-facade-ceiling-roadmap.md "
        "for the demand-gating procedure"
    )
    assert not missing, f"facade(s) removed: {sorted(missing)}"


def test_inventory_stays_under_v2_0_ceiling() -> None:
    """v2.0 facade ceiling is 40 ergonomic facades. Combined with the
    12 primitives/operators we currently ship, the absolute upper bound
    is 52 tools. Trip this assertion long before the wire surface gets
    out of hand.
    """
    actual = _enumerate_tools()
    assert len(actual) <= 52, (
        f"facade+primitive count ({len(actual)}) exceeds v2.0 ceiling 52; "
        "consolidate or split the registry per the v2.0 roadmap"
    )


@pytest.mark.parametrize("tool_name", sorted(EXPECTED_TOOLS))
def test_facade_class_resolvable_by_snake_name(tool_name: str) -> None:
    """Cross-check that every allow-listed tool has a discoverable class.

    Serves as a smoke test for the introspection used by the v1.9.2
    Item C shadow-workspace dispatcher — if a tool is in the allow-list
    but the introspection misses it, the shadow path silently falls back
    to the legacy ``_FACADE_DISPATCH`` table and we lose isolation.
    """
    actual = set(_enumerate_tools())
    assert tool_name in actual, f"{tool_name!r} declared in EXPECTED_TOOLS but not discoverable"
