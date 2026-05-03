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
    """Enumerate Scalpel facade/primitive tools by their canonical
    snake-case name.

    v2.0 (spec 2026-05-03 § 5.1): the ``scalpel_`` class-name prefix was
    dropped. Discovery now filters by source module + ``Tool`` suffix +
    ``Tool`` subclass relation, instead of the old ``startswith("Scalpel")``
    test.
    """
    from serena.tools.tools_base import Tool

    seen: set[str] = set()
    out: list[str] = []
    for module in (scalpel_facades, scalpel_primitives):
        for name in dir(module):
            if not name.endswith("Tool"):
                continue
            cls = getattr(module, name)
            if not isinstance(cls, type):
                continue
            # Only count classes that are concrete Tool subclasses defined
            # in this module (not re-exported helpers like ``Tool`` itself).
            if not issubclass(cls, Tool) or cls is Tool:
                continue
            if cls.__module__ != module.__name__:
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
    "annotate_return_type",
    "apply_capability",
    "auto_import_specialized",
    "capabilities_list",
    "capability_describe",
    "change_return_type",
    "change_type_shape",
    "change_visibility",
    "complete_match_arms",
    "confirm_annotations",
    "convert_from_relative_imports",
    "convert_module_layout",
    "convert_to_async",
    "convert_to_method_object",
    "dry_run_compose",
    "execute_command",
    "expand_glob_imports",
    "expand_macro",
    "extract",
    "extract_lifetime",
    "extract_section",
    "fix_lints",
    "generate_constructor",
    "generate_from_undefined",
    "generate_member",
    "generate_trait_impl_scaffold",
    "ignore_diagnostic",
    "imports_organize",
    "inline",
    "install_lsp_servers",
    "introduce_parameter",
    "local_to_field",
    "organize_links",
    "override_methods",
    "reload_plugins",
    "rename",
    "rename_heading",
    "rollback",
    "split_doc",
    "split_file",
    "tidy_structure",
    "transaction_commit",
    "transaction_rollback",
    "use_function",
    "verify_after_refactor",
    "workspace_health",
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
