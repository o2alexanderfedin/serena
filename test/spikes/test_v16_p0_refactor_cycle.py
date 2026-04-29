"""v1.6 PR 1 / Plan 0 — Break the scalpel_primitives <-> scalpel_facades import cycle.

RED tests:
1. ``test_facade_support_exports_apply_helpers`` — the lifted functions +
   ``_SNAPSHOT_NONEXISTENT`` sentinel must import directly from
   ``serena.tools.facade_support``.
2. ``test_no_lazy_import_in_dispatch_via_coordinator`` — AST-scan
   ``scalpel_primitives._dispatch_via_coordinator`` (and the related
   ``ScalpelConfirmAnnotationsTool.apply``) and assert no
   ``from .scalpel_facades import`` lazy-import remains in the body.
3. ``test_existing_apply_call_sites_still_work`` — sanity: the existing
   Stage 2A T1 ``test_stage_2a_t1_facade_support.py`` smoke still imports
   cleanly so the lift didn't break the public ``facade_support`` surface.

Plan source: docs/superpowers/plans/2026-04-29-stub-facade-fix/IMPLEMENTATION-PLANS.md
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path


def test_facade_support_exports_apply_helpers() -> None:
    """All five lifted symbols must be importable from facade_support."""
    from serena.tools.facade_support import (  # noqa: F401
        _SNAPSHOT_NONEXISTENT,
        _apply_text_edits_to_file_uri,
        _apply_workspace_edit_to_disk,
        _resolve_winner_edit,
        _uri_to_path,
    )
    # Sanity-check the sentinel: it must be a hashable, distinguishable marker
    # so snapshot dicts can carry "file did not exist pre-edit" without
    # colliding with any real string content.
    assert _SNAPSHOT_NONEXISTENT is not None
    assert _SNAPSHOT_NONEXISTENT != ""


def _function_def_in_module(
    module_path: Path, qualname: str
) -> ast.FunctionDef:
    """Locate a top-level function or method definition inside ``module_path``.

    ``qualname`` may be ``"foo"`` (top-level function) or
    ``"ClassName.method"`` (method on a class). Raises ``LookupError`` if
    not found so the test fails with a clear message.
    """
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    parts = qualname.split(".")
    if len(parts) == 1:
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == parts[0]:
                return node
    elif len(parts) == 2:
        cls_name, method_name = parts
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == cls_name:
                for sub in node.body:
                    if (
                        isinstance(sub, ast.FunctionDef)
                        and sub.name == method_name
                    ):
                        return sub
    raise LookupError(f"Could not find {qualname!r} in {module_path}")


def _has_lazy_import_from_scalpel_facades(fn: ast.FunctionDef) -> bool:
    """Return True if ``fn``'s body contains a ``from .scalpel_facades import``
    or ``from serena.tools.scalpel_facades import`` statement at any depth.
    """
    for node in ast.walk(fn):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.endswith("scalpel_facades"):
                return True
    return False


def _module_path() -> Path:
    spec = importlib.util.find_spec("serena.tools.scalpel_primitives")
    assert spec is not None and spec.origin is not None
    return Path(spec.origin)


def test_no_lazy_import_in_dispatch_via_coordinator() -> None:
    """``_dispatch_via_coordinator`` must not lazy-import from scalpel_facades."""
    fn = _function_def_in_module(_module_path(), "_dispatch_via_coordinator")
    assert not _has_lazy_import_from_scalpel_facades(fn), (
        "_dispatch_via_coordinator still contains a lazy "
        "`from .scalpel_facades import ...` — Plan 0 requires the import "
        "to be lifted to the module top via facade_support."
    )


def test_no_lazy_import_in_confirm_annotations_apply() -> None:
    """``ScalpelConfirmAnnotationsTool.apply`` must not lazy-import either.

    Plan 0 explicitly cites ``_dispatch_via_coordinator`` in its RED test
    list, but the actual surviving lazy import in trunk is in
    ``ScalpelConfirmAnnotationsTool.apply`` (see
    ``scalpel_primitives.py:618``). We extend the RED contract here so
    the cycle is *actually* broken — not just nominally on the named
    function.
    """
    fn = _function_def_in_module(
        _module_path(), "ScalpelConfirmAnnotationsTool.apply"
    )
    assert not _has_lazy_import_from_scalpel_facades(fn), (
        "ScalpelConfirmAnnotationsTool.apply still contains a lazy "
        "`from .scalpel_facades import ...` — Plan 0 requires it lifted "
        "via facade_support so primitives don't depend on facades."
    )


def test_existing_apply_call_sites_still_work() -> None:
    """Sanity: existing Stage 2A T1 facade_support smoke still imports.

    If we accidentally broke the public facade_support surface, this
    import would raise ImportError before pytest can even collect the
    older test file. We re-trigger the import here as a structural
    canary; the actual Stage 2A T1 suite is run separately by the
    regression sweep.
    """
    from serena.tools.facade_support import (  # noqa: F401
        FACADE_TO_CAPABILITY_ID,
        apply_workspace_edit_via_editor,
        build_failure_result,
        record_checkpoint_for_workspace_edit,
        resolve_capability_for_facade,
        workspace_boundary_guard,
    )
