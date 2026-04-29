"""v1.6 P5 / Plan 5 — facade docstring invariants.

Three families of assertions on the Scalpel* tool docstrings:

1. **Per-facade ``informational`` tag tests** (12 + 8 = 20 individual tests):
   for each of the 12 user-facing facades whose ``apply()`` deletes a
   user-facing parameter, the class docstring MUST mention the parameter
   name AND the substring ``informational``. 8 additional tags cover
   ``split_file.groups`` (Rust + Python), ``expand_macro.dry_run``,
   ``verify_after_refactor.dry_run``, ``apply_capability.params``,
   ``generate_constructor.include_fields``,
   ``override_methods.method_names``, and ``rename.also_in_strings``.

2. **2 rollback success-contract tests**: ``ScalpelRollbackTool`` and
   ``ScalpelTransactionRollbackTool`` docstrings each MUST contain the
   phrase ``Restores edits to disk`` and the word ``snapshot`` so the LLM
   caller knows rollback writes pre-edit content back to disk (v1.7 P7
   landed the on-disk inverse-applier — replaced the v1.6 ``WARNING:``
   block).

3. **Drift-CI gate** (``test_dropped_params_carry_informational_tag``):
   AST-scan every ``Scalpel*Tool.apply()`` body for ``del <name>``
   statements. For every dropped name that is NOT a recognised technical
   parameter (``preview_token``, ``language``, ``dry_run``), assert the
   class docstring contains the parameter name AND ``informational``.
   This gate prevents future regressions where a maintainer adds a new
   ``del <param>`` without the corresponding docstring honesty. (The
   rollback pair carries no ``del`` statements after v1.7 P7, so the
   special-case ``WARNING:`` opener-tag exception was retired.)

Plan source: docs/superpowers/plans/2026-04-29-stub-facade-fix/IMPLEMENTATION-PLANS.md  Plan 5
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from serena.tools import scalpel_facades, scalpel_primitives

# ---------------------------------------------------------------------------
# Per-facade informational-tag tests (the 12-facade A4 cluster)
# ---------------------------------------------------------------------------

# (class_obj_path, dropped_param_name) — explicit list per Plan 5.
_INFORMATIONAL_TAGS: tuple[tuple[str, str], ...] = (
    # 12 informational-cluster facades:
    ("scalpel_facades.ScalpelChangeVisibilityTool", "target_visibility"),
    ("scalpel_facades.ScalpelChangeReturnTypeTool", "new_return_type"),
    ("scalpel_facades.ScalpelExtractLifetimeTool", "lifetime_name"),
    ("scalpel_facades.ScalpelGenerateTraitImplScaffoldTool", "trait_name"),
    ("scalpel_facades.ScalpelIntroduceParameterTool", "parameter_name"),
    ("scalpel_facades.ScalpelGenerateFromUndefinedTool", "target_kind"),
    ("scalpel_facades.ScalpelAutoImportSpecializedTool", "symbol_name"),
    ("scalpel_facades.ScalpelIgnoreDiagnosticTool", "rule"),
    ("scalpel_facades.ScalpelExtractTool", "new_name"),
    ("scalpel_facades.ScalpelInlineTool", "name_path"),
    ("scalpel_facades.ScalpelImportsOrganizeTool", "add_missing"),
    ("scalpel_facades.ScalpelTidyStructureTool", "scope"),
    # 8 additional docstring tags:
    ("scalpel_facades.ScalpelSplitFileTool", "groups"),
    ("scalpel_facades.ScalpelExpandMacroTool", "dry_run"),
    ("scalpel_facades.ScalpelVerifyAfterRefactorTool", "dry_run"),
    ("scalpel_primitives.ScalpelApplyCapabilityTool", "params"),
    ("scalpel_facades.ScalpelGenerateConstructorTool", "include_fields"),
    ("scalpel_facades.ScalpelOverrideMethodsTool", "method_names"),
    ("scalpel_facades.ScalpelRenameTool", "also_in_strings"),
)


def _resolve_class(qualified: str) -> type:
    mod_name, cls_name = qualified.split(".", 1)
    mod = {
        "scalpel_facades": scalpel_facades,
        "scalpel_primitives": scalpel_primitives,
    }[mod_name]
    return getattr(mod, cls_name)


def _full_docstring(cls: type) -> str:
    """Concatenate the class docstring + the ``apply`` method docstring.

    The docstring opener may live on either the class (recommended) or the
    ``apply`` method (acceptable). Drift-CI scans both.
    """
    parts: list[str] = []
    if cls.__doc__:
        parts.append(cls.__doc__)
    apply = cls.__dict__.get("apply")
    if apply is not None and apply.__doc__:
        parts.append(apply.__doc__)
    return "\n".join(parts)


@pytest.mark.parametrize("qualified,param", _INFORMATIONAL_TAGS)
def test_facade_informational_tag(qualified: str, param: str) -> None:
    cls = _resolve_class(qualified)
    doc = _full_docstring(cls)
    assert param in doc, (
        f"{qualified} docstring missing parameter name {param!r}"
    )
    assert "informational" in doc.lower(), (
        f"{qualified} docstring missing 'informational' tag for {param!r}"
    )


# ---------------------------------------------------------------------------
# Rollback success-contract tests (2) — v1.7 P7 replaced the v1.6 ``WARNING:``
# block with a real on-disk inverse-applier; the gate now asserts the new
# success-contract phrasing.
# ---------------------------------------------------------------------------

_ROLLBACK_TOOLS: tuple[type, ...] = (
    scalpel_primitives.ScalpelRollbackTool,
    scalpel_primitives.ScalpelTransactionRollbackTool,
)


@pytest.mark.parametrize("cls", _ROLLBACK_TOOLS)
def test_rollback_success_contract_phrasing_present(cls: type) -> None:
    """v1.7 P7 — rollback docstrings must advertise the on-disk restore
    contract (replaced the v1.6 ``WARNING: does NOT undo`` block)."""
    doc = _full_docstring(cls)
    assert "Restores edits to disk" in doc, (
        f"{cls.__name__} docstring missing the 'Restores edits to disk' "
        f"success-contract phrase introduced by v1.7 P7."
    )
    assert "snapshot" in doc.lower(), (
        f"{cls.__name__} docstring missing the 'snapshot' wording — the "
        f"caller needs to know rollback uses the captured pre-edit snapshot."
    )
    # Defence in depth: the v1.6 ``WARNING: does NOT undo`` lie must NOT
    # creep back in after the v1.7 P7 fix.
    assert "does NOT undo" not in doc, (
        f"{cls.__name__} docstring still carries the v1.6 'does NOT undo' "
        f"phrasing; v1.7 P7 made rollback restore to disk — update the "
        f"docstring to match the new contract."
    )


# ---------------------------------------------------------------------------
# Drift CI gate — every ``del <name>`` line carries an informational tag
# ---------------------------------------------------------------------------

# Technical parameters that the contract universally treats as
# infrastructure (not user-facing knobs); we don't require an
# informational tag for these.
_TECHNICAL_PARAM_NAMES: frozenset[str] = frozenset({
    "preview_token", "language", "dry_run",
    # ``ScalpelSplitFileTool`` deletes 5 layout/policy params alongside
    # ``groups``; the v1.6 doc-tag focuses on the headline ``groups``
    # symbol-list ablation. The 5 layout/policy params are documented
    # via the docstring's ``v1.6 informational`` block but their names
    # don't need to be re-spelled in the gate scan.
    "parent_layout", "keep_in_original", "reexport_policy",
    "explicit_reexports", "allow_partial",
    # Primitives — already in-source comment-tagged as reserved/escape-hatch
    # technical parameters (``ScalpelCapabilitiesListTool.applies_to_symbol_kind``,
    # ``ScalpelExecuteCommandTool.allow_out_of_workspace``). Not user-facing
    # contract knobs.
    "applies_to_symbol_kind", "allow_out_of_workspace",
})


def _collect_dropped_user_params(module) -> list[tuple[type, str]]:
    """For each ``Scalpel*Tool`` class with an ``apply()`` method, return
    every ``del <name>`` target that is not in the technical-param
    whitelist. Used by the drift CI gate.
    """
    src = Path(inspect.getfile(module)).read_text(encoding="utf-8")
    tree = ast.parse(src)
    out: list[tuple[type, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not node.name.startswith("Scalpel"):
            continue
        cls = getattr(module, node.name, None)
        if cls is None:
            continue
        for item in node.body:
            if not (isinstance(item, ast.FunctionDef) and item.name == "apply"):
                continue
            for stmt in item.body:
                if not isinstance(stmt, ast.Delete):
                    continue
                for tgt in stmt.targets:
                    if not isinstance(tgt, ast.Name):
                        continue
                    if tgt.id in _TECHNICAL_PARAM_NAMES:
                        continue
                    out.append((cls, tgt.id))
    return out


def _all_dropped_user_params() -> list[tuple[type, str]]:
    items: list[tuple[type, str]] = []
    items.extend(_collect_dropped_user_params(scalpel_facades))
    items.extend(_collect_dropped_user_params(scalpel_primitives))
    return items


@pytest.mark.parametrize(
    "cls,param",
    _all_dropped_user_params(),
    ids=lambda v: v.__name__ if isinstance(v, type) else str(v),
)
def test_dropped_params_carry_informational_tag(cls: type, param: str) -> None:
    """Drift gate: every user-facing ``del <name>`` must be opener-tagged
    in the class docstring as ``informational``.

    v1.7 P7 retired the rollback-pair ``WARNING:`` exception because those
    tools no longer drop user-facing params after the on-disk inverse-applier
    landed. Should a future rollback tool introduce a ``del <param>``, the
    standard ``informational`` tag applies.
    """
    doc = _full_docstring(cls)
    assert param in doc, (
        f"{cls.__name__}.apply() drops user-facing param {param!r} but "
        f"the docstring never mentions it. Add an 'informational' note."
    )
    assert "informational" in doc.lower(), (
        f"{cls.__name__}.apply() drops user-facing param {param!r} but "
        f"the docstring lacks the expected 'informational' opener-tag."
    )
