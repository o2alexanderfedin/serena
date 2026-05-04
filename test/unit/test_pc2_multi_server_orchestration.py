"""PC2 coverage uplift — serena.refactoring.multi_server orchestration.

Targets uncovered line ranges identified in Phase B coverage analysis:
- L132-139  _default_broadcast_timeout_ms env-var parsing
- L196-201  _normalize_kind suffix detection
- L257-275  _apply_priority disabled/active partition + unknown-family fallback
- L296-329  _apply_priority winner selection + disabled preservation
- L360-369  _normalize_title prefix stripping
- L380-413  _workspace_edit_to_canonical_set (documentChanges + legacy changes)
- L418      _workspace_edits_equal
- L439-494  _dedup clustering (title + edit equality)
- L520-613  _iter_text_document_edits + _check_apply_clean + _check_syntactic_validity
- L616-657  _check_workspace_boundary
- L678-717  _reconcile_rename_edits surgical vs whole-file shape
- L720-736  _line_hunks difflib output
- L739-757  _rename_symdiff
- L1040-1099 MultiServerCoordinator.broadcast (timeout path, error path)
- L1101-1115 _resolve_if_needed (has_edit, has_command, fallback)
- L1117-1263 merge_code_actions (full path with real FakeServer)
- L1428-1501 merge_rename (debug path, loser=None, loser_error)
- L1631-1639 get_action_edit
- L1697-1743 expand_macro, fetch_runnables, run_flycheck
- L1746-1766 _split_name_path, _to_relative_path
- L1797-1839 _walk_document_symbols_for_range
- L1842-1930 EditAttributionLog

All tests are pure unit-level — no real LSP processes spawned.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from serena.refactoring._async_check import AWAITED_SERVER_METHODS
from serena.refactoring.multi_server import (
    EditAttributionLog,
    MultiServerCoordinator,
    _PRIORITY_TABLE,
    _apply_priority,
    _check_apply_clean,
    _check_syntactic_validity,
    _classify_quickfix_context,
    _dedup,
    _default_broadcast_timeout_ms,
    _iter_text_document_edits,
    _line_hunks,
    _normalize_kind,
    _normalize_title,
    _reconcile_rename_edits,
    _rename_symdiff,
    _split_name_path,
    _to_relative_path,
    _uri_to_path,
    _walk_document_symbols_for_range,
    _workspace_edit_to_canonical_set,
    _workspace_edits_equal,
)
from solidlsp.dynamic_capabilities import DynamicCapabilityRegistry


# ---------------------------------------------------------------------------
# Helpers to build fake async-compatible servers
# ---------------------------------------------------------------------------


def _make_async_server(server_id: str, caps: dict[str, Any] | None = None) -> MagicMock:
    """Create a MagicMock server that passes async callable checks."""
    server = MagicMock()
    for method_name in AWAITED_SERVER_METHODS:
        getattr(server, method_name)._o2_async_callable = True
    server.server_id = server_id
    server.server_capabilities = MagicMock(return_value=caps or {})
    return server


def _make_coord(
    servers: dict[str, MagicMock],
    caps_per_server: dict[str, Any] | None = None,
) -> MultiServerCoordinator:
    """Create a MultiServerCoordinator with an empty dynamic registry."""
    return MultiServerCoordinator(
        servers=servers,
        dynamic_registry=DynamicCapabilityRegistry(),
        catalog=None,
    )


# ---------------------------------------------------------------------------
# _default_broadcast_timeout_ms
# ---------------------------------------------------------------------------


class TestDefaultBroadcastTimeoutMs:
    def test_default_is_2000(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("O2_SCALPEL_BROADCAST_TIMEOUT_MS", None)
            result = _default_broadcast_timeout_ms()
        assert result == 2000

    def test_env_var_override(self) -> None:
        with patch.dict(os.environ, {"O2_SCALPEL_BROADCAST_TIMEOUT_MS": "5000"}):
            result = _default_broadcast_timeout_ms()
        assert result == 5000

    def test_invalid_env_var_falls_back_to_2000(self) -> None:
        with patch.dict(os.environ, {"O2_SCALPEL_BROADCAST_TIMEOUT_MS": "notanumber"}):
            result = _default_broadcast_timeout_ms()
        assert result == 2000

    def test_zero_env_var_falls_back_to_2000(self) -> None:
        with patch.dict(os.environ, {"O2_SCALPEL_BROADCAST_TIMEOUT_MS": "0"}):
            result = _default_broadcast_timeout_ms()
        assert result == 2000

    def test_negative_env_var_falls_back_to_2000(self) -> None:
        with patch.dict(os.environ, {"O2_SCALPEL_BROADCAST_TIMEOUT_MS": "-500"}):
            result = _default_broadcast_timeout_ms()
        assert result == 2000


# ---------------------------------------------------------------------------
# _normalize_kind
# ---------------------------------------------------------------------------


class TestNormalizeKind:
    def test_source_organize_imports_ruff(self) -> None:
        assert _normalize_kind("source.organizeImports.ruff") == "source.organizeImports"

    def test_source_fix_all_ruff(self) -> None:
        assert _normalize_kind("source.fixAll.ruff") == "source.fixAll"

    def test_refactor_extract_function_preserved(self) -> None:
        # Not a server suffix — kept as-is.
        assert _normalize_kind("refactor.extract.function") == "refactor.extract.function"

    def test_bare_quickfix_preserved(self) -> None:
        assert _normalize_kind("quickfix") == "quickfix"

    def test_empty_string_preserved(self) -> None:
        assert _normalize_kind("") == ""

    def test_no_dot_preserved(self) -> None:
        assert _normalize_kind("refactor") == "refactor"

    def test_unknown_family_preserved(self) -> None:
        # Head isn't a known base family.
        assert _normalize_kind("myextension.thing.ruff") == "myextension.thing.ruff"

    def test_unknown_suffix_preserved(self) -> None:
        # Tail isn't a known server suffix.
        assert _normalize_kind("source.organizeImports.unknownserver") == "source.organizeImports.unknownserver"

    def test_pylsp_rope_suffix(self) -> None:
        assert _normalize_kind("refactor.extract.pylsp-rope") == "refactor.extract"

    def test_basedpyright_suffix(self) -> None:
        assert _normalize_kind("source.organizeImports.basedpyright") == "source.organizeImports"


# ---------------------------------------------------------------------------
# _classify_quickfix_context
# ---------------------------------------------------------------------------


class TestClassifyQuickfixContext:
    def test_none_diagnostic_is_other(self) -> None:
        assert _classify_quickfix_context(None) == "other"

    def test_empty_dict_is_other(self) -> None:
        assert _classify_quickfix_context({}) == "other"

    def test_no_code_is_other(self) -> None:
        assert _classify_quickfix_context({"message": "foo"}) == "other"

    def test_auto_import_code(self) -> None:
        assert _classify_quickfix_context({"code": "undefined-name"}) == "auto-import"

    def test_basedpyright_undefined_variable(self) -> None:
        assert _classify_quickfix_context({"code": "reportUndefinedVariable"}) == "auto-import"

    def test_ruff_f821(self) -> None:
        assert _classify_quickfix_context({"code": "F821"}) == "auto-import"

    def test_type_error_exact(self) -> None:
        assert _classify_quickfix_context({"code": "type-error"}) == "type-error"

    def test_report_prefix_is_type_error(self) -> None:
        assert _classify_quickfix_context({"code": "reportArgumentType"}) == "type-error"

    def test_lint_fix_e_prefix(self) -> None:
        assert _classify_quickfix_context({"code": "E401"}) == "lint-fix"

    def test_lint_fix_w_prefix(self) -> None:
        assert _classify_quickfix_context({"code": "W291"}) == "lint-fix"

    def test_lint_fix_f_prefix(self) -> None:
        assert _classify_quickfix_context({"code": "F401"}) == "lint-fix"

    def test_lint_fix_b_prefix(self) -> None:
        assert _classify_quickfix_context({"code": "B001"}) == "lint-fix"

    def test_numeric_code_is_other(self) -> None:
        # Pure numeric code that doesn't start with known prefix.
        assert _classify_quickfix_context({"code": 404}) == "other"

    def test_prefix_without_digit_is_other(self) -> None:
        # "E" alone without digit following is not matched.
        assert _classify_quickfix_context({"code": "E"}) == "other"


# ---------------------------------------------------------------------------
# _apply_priority
# ---------------------------------------------------------------------------


class TestApplyPriority:
    def test_empty_candidates(self) -> None:
        assert _apply_priority([], family="quickfix", quickfix_context=None) == []

    def test_winner_selected_by_priority(self) -> None:
        candidates = [
            ("pylsp-rope", {"title": "fix a", "kind": "quickfix"}),
            ("ruff", {"title": "fix b", "kind": "quickfix"}),
        ]
        # For quickfix/lint-fix: ruff > pylsp-rope
        result = _apply_priority(candidates, family="quickfix", quickfix_context="lint-fix")
        assert result[0][0] == "ruff"

    def test_disabled_actions_preserved(self) -> None:
        disabled_action = {
            "title": "disabled fix",
            "disabled": {"reason": "not available"},
        }
        active_action = {"title": "active fix"}
        candidates = [
            ("pylsp-rope", active_action),
            ("ruff", disabled_action),
        ]
        result = _apply_priority(candidates, family="quickfix", quickfix_context="lint-fix")
        # Active winner + disabled preserved at end.
        assert len(result) == 2
        sids = [sid for sid, _ in result]
        assert "ruff" in sids  # disabled ruff preserved
        # Active winner should be ruff for lint-fix; but ruff is disabled here.
        # pylsp-rope is the only active candidate.
        assert result[0][0] == "pylsp-rope"

    def test_unknown_family_falls_back_to_first_active(self) -> None:
        candidates = [
            ("some-server", {"title": "fix"}),
        ]
        result = _apply_priority(candidates, family="unknown.family", quickfix_context=None)
        assert len(result) == 1
        assert result[0][0] == "some-server"

    def test_no_priority_match_returns_first_active(self) -> None:
        # All servers have no entry in priority table for this family.
        candidates = [
            ("unknown-server-1", {"title": "fix 1"}),
            ("unknown-server-2", {"title": "fix 2"}),
        ]
        result = _apply_priority(candidates, family="source.organizeImports", quickfix_context=None)
        # unknown servers not in priority list → first active surfaced.
        assert result[0][0] == "unknown-server-1"

    def test_all_disabled_returns_only_disabled(self) -> None:
        d1 = {"title": "d1", "disabled": {"reason": "r1"}}
        d2 = {"title": "d2", "disabled": {"reason": "r2"}}
        candidates = [("pylsp-rope", d1), ("ruff", d2)]
        result = _apply_priority(candidates, family="source.organizeImports", quickfix_context=None)
        # No active winner; only disabled preserved.
        assert len(result) == 2
        assert all(isinstance(a.get("disabled"), dict) for _, a in result)

    def test_source_organize_imports_ruff_wins(self) -> None:
        candidates = [
            ("basedpyright", {"title": "organize imports"}),
            ("ruff", {"title": "organize imports"}),
            ("pylsp-rope", {"title": "organize imports"}),
        ]
        result = _apply_priority(candidates, family="source.organizeImports", quickfix_context=None)
        assert result[0][0] == "ruff"


# ---------------------------------------------------------------------------
# _normalize_title
# ---------------------------------------------------------------------------


class TestNormalizeTitle:
    def test_lowercase(self) -> None:
        assert _normalize_title("FIX THIS") == "fix this"

    def test_strip_quick_fix_prefix(self) -> None:
        # "quick fix: add import" → strip "quick fix: " → "add import"
        # then strip "add " → "import"
        assert _normalize_title("quick fix: add import") == "import"

    def test_strip_add_prefix(self) -> None:
        assert _normalize_title("Add: numpy") == "numpy"

    def test_strip_fix_prefix(self) -> None:
        assert _normalize_title("fix: missing comma") == "missing comma"

    def test_collapse_whitespace(self) -> None:
        assert _normalize_title("add   extra  spaces") == "extra spaces"

    def test_strip_add_space_prefix(self) -> None:
        assert _normalize_title("add import for numpy") == "import for numpy"

    def test_repeated_prefix_stripping(self) -> None:
        # Repeated stripping: "add: add: x" → after first strip "add: x" → after second "x"
        assert _normalize_title("add: add: x") == "x"

    def test_empty_string(self) -> None:
        assert _normalize_title("") == ""


# ---------------------------------------------------------------------------
# _workspace_edit_to_canonical_set
# ---------------------------------------------------------------------------


class TestWorkspaceEditToCanonicalSet:
    def test_document_changes_text_edit(self) -> None:
        edit = {
            "documentChanges": [{
                "textDocument": {"uri": "file:///foo.py"},
                "edits": [{
                    "range": {
                        "start": {"line": 1, "character": 0},
                        "end": {"line": 1, "character": 5},
                    },
                    "newText": "hello",
                }],
            }],
        }
        result = _workspace_edit_to_canonical_set(edit)
        assert len(result) == 1
        assert ("file:///foo.py", 1, 0, 1, 5, "hello") in result

    def test_document_changes_create_file(self) -> None:
        edit = {
            "documentChanges": [{
                "kind": "create",
                "uri": "file:///new.py",
            }],
        }
        result = _workspace_edit_to_canonical_set(edit)
        assert ("create", "file:///new.py") in result

    def test_document_changes_delete_file(self) -> None:
        edit = {
            "documentChanges": [{
                "kind": "delete",
                "uri": "file:///old.py",
            }],
        }
        result = _workspace_edit_to_canonical_set(edit)
        assert ("delete", "file:///old.py") in result

    def test_document_changes_rename_file(self) -> None:
        edit = {
            "documentChanges": [{
                "kind": "rename",
                "oldUri": "file:///old.py",
                "newUri": "file:///new.py",
            }],
        }
        result = _workspace_edit_to_canonical_set(edit)
        assert ("rename", "file:///old.py", "file:///new.py") in result

    def test_legacy_changes_map(self) -> None:
        edit = {
            "changes": {
                "file:///bar.py": [{
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 3},
                    },
                    "newText": "new",
                }],
            },
        }
        result = _workspace_edit_to_canonical_set(edit)
        assert ("file:///bar.py", 0, 0, 0, 3, "new") in result

    def test_empty_edit(self) -> None:
        result = _workspace_edit_to_canonical_set({})
        assert result == frozenset()

    def test_order_independence(self) -> None:
        """Two edits with same content but different order produce same set."""
        e1 = {
            "changes": {
                "file:///x.py": [
                    {"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}}, "newText": "a"},
                    {"range": {"start": {"line": 1, "character": 0}, "end": {"line": 1, "character": 0}}, "newText": "b"},
                ],
            },
        }
        e2 = {
            "changes": {
                "file:///x.py": [
                    {"range": {"start": {"line": 1, "character": 0}, "end": {"line": 1, "character": 0}}, "newText": "b"},
                    {"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}}, "newText": "a"},
                ],
            },
        }
        assert _workspace_edit_to_canonical_set(e1) == _workspace_edit_to_canonical_set(e2)


# ---------------------------------------------------------------------------
# _workspace_edits_equal
# ---------------------------------------------------------------------------


class TestWorkspaceEditsEqual:
    def test_equal_edits(self) -> None:
        edit = {
            "changes": {
                "file:///x.py": [{
                    "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 5}},
                    "newText": "hello",
                }],
            },
        }
        assert _workspace_edits_equal(edit, edit) is True

    def test_different_edits(self) -> None:
        e1 = {"changes": {"file:///x.py": [{"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}}, "newText": "a"}]}}
        e2 = {"changes": {"file:///x.py": [{"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}}, "newText": "b"}]}}
        assert _workspace_edits_equal(e1, e2) is False


# ---------------------------------------------------------------------------
# _dedup
# ---------------------------------------------------------------------------


class TestDedup:
    def test_single_candidate(self) -> None:
        candidates = [("pylsp-rope", {"title": "fix"})]
        result = _dedup(candidates, priority=("pylsp-rope", "ruff"))
        assert len(result) == 1
        sid, action, dropped = result[0]
        assert sid == "pylsp-rope"
        assert dropped == []

    def test_empty_candidates(self) -> None:
        result = _dedup([], priority=())
        assert result == []

    def test_duplicate_title_keeps_higher_priority(self) -> None:
        # Both have identical exact titles → duplicate_title match.
        candidates = [
            ("pylsp-rope", {"title": "Import numpy"}),
            ("basedpyright", {"title": "Import numpy"}),
        ]
        priority = ("basedpyright", "pylsp-rope")
        result = _dedup(candidates, priority=priority)
        # basedpyright is higher priority → should win
        assert len(result) == 1
        sid, action, dropped = result[0]
        assert sid == "basedpyright"
        assert len(dropped) == 1
        assert dropped[0][2] == "duplicate_title"

    def test_duplicate_edit_dedup(self) -> None:
        shared_edit = {
            "changes": {
                "file:///x.py": [{
                    "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 3}},
                    "newText": "new",
                }],
            },
        }
        candidates = [
            ("pylsp-rope", {"title": "Action A", "edit": shared_edit}),
            ("basedpyright", {"title": "Action B", "edit": shared_edit}),
        ]
        priority = ("pylsp-rope", "basedpyright")
        result = _dedup(candidates, priority=priority)
        assert len(result) == 1
        sid, _, dropped = result[0]
        assert sid == "pylsp-rope"
        assert dropped[0][2] == "duplicate_edit"

    def test_distinct_titles_and_edits_kept(self) -> None:
        # Use distinct edits with different URIs so they're NOT equal.
        edit_a = {
            "changes": {"file:///a.py": [{"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}}, "newText": "x"}]},
        }
        edit_b = {
            "changes": {"file:///b.py": [{"range": {"start": {"line": 5, "character": 0}, "end": {"line": 5, "character": 1}}, "newText": "y"}]},
        }
        candidates = [
            ("pylsp-rope", {"title": "Action A", "edit": edit_a}),
            ("ruff", {"title": "Action B", "edit": edit_b}),
        ]
        priority = ("pylsp-rope", "ruff")
        result = _dedup(candidates, priority=priority)
        assert len(result) == 2

    def test_empty_title_not_deduplicated(self) -> None:
        """Empty titles should NOT trigger title-based dedup (§11.1 Stage-2)."""
        candidates = [
            ("pylsp-rope", {"title": ""}),
            ("basedpyright", {"title": ""}),
        ]
        priority = ("pylsp-rope", "basedpyright")
        result = _dedup(candidates, priority=priority)
        # Empty titles don't match — both survive.
        assert len(result) == 2


# ---------------------------------------------------------------------------
# _iter_text_document_edits
# ---------------------------------------------------------------------------


class TestIterTextDocumentEdits:
    def test_document_changes_shape(self) -> None:
        edit = {
            "documentChanges": [
                {"textDocument": {"uri": "file:///a.py"}, "edits": [{"range": {}, "newText": "x"}]},
                {"kind": "create", "uri": "file:///new.py"},  # no textDocument → skipped
            ],
        }
        from serena.refactoring.multi_server import _iter_text_document_edits
        result = _iter_text_document_edits(edit)
        assert len(result) == 1
        assert result[0]["textDocument"]["uri"] == "file:///a.py"

    def test_legacy_changes_map(self) -> None:
        from serena.refactoring.multi_server import _iter_text_document_edits
        edit = {
            "changes": {
                "file:///b.py": [{"range": {}, "newText": "y"}],
            },
        }
        result = _iter_text_document_edits(edit)
        assert len(result) == 1
        assert result[0]["textDocument"]["uri"] == "file:///b.py"

    def test_empty_edit(self) -> None:
        from serena.refactoring.multi_server import _iter_text_document_edits
        assert _iter_text_document_edits({}) == []


# ---------------------------------------------------------------------------
# _check_apply_clean
# ---------------------------------------------------------------------------


class TestCheckApplyClean:
    def test_version_matches(self) -> None:
        edit = {
            "documentChanges": [{
                "textDocument": {"uri": "file:///x.py", "version": 3},
                "edits": [],
            }],
        }
        ok, reason = _check_apply_clean(edit, {"file:///x.py": 3})
        assert ok is True
        assert reason is None

    def test_version_mismatch(self) -> None:
        edit = {
            "documentChanges": [{
                "textDocument": {"uri": "file:///x.py", "version": 2},
                "edits": [],
            }],
        }
        ok, reason = _check_apply_clean(edit, {"file:///x.py": 5})
        assert ok is False
        assert "STALE_VERSION" in (reason or "")

    def test_no_version_in_edit(self) -> None:
        edit = {
            "documentChanges": [{
                "textDocument": {"uri": "file:///x.py", "version": None},
                "edits": [],
            }],
        }
        ok, reason = _check_apply_clean(edit, {"file:///x.py": 5})
        assert ok is True

    def test_unknown_uri_skipped(self) -> None:
        edit = {
            "documentChanges": [{
                "textDocument": {"uri": "file:///unknown.py", "version": 1},
                "edits": [],
            }],
        }
        ok, reason = _check_apply_clean(edit, {})
        assert ok is True


# ---------------------------------------------------------------------------
# _check_syntactic_validity (pure in-memory)
# ---------------------------------------------------------------------------


class TestCheckSyntacticValidity:
    def test_valid_python_edit(self, tmp_path: Path) -> None:
        f = tmp_path / "x.py"
        f.write_text("x = 1\n")
        edit = {
            "documentChanges": [{
                "textDocument": {"uri": f.as_uri()},
                "edits": [{
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 5},
                    },
                    "newText": "y = 2",
                }],
            }],
        }
        ok, reason = _check_syntactic_validity(edit)
        assert ok is True
        assert reason is None

    def test_invalid_python_edit(self, tmp_path: Path) -> None:
        f = tmp_path / "x.py"
        f.write_text("x = 1\n")
        edit = {
            "documentChanges": [{
                "textDocument": {"uri": f.as_uri()},
                "edits": [{
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 5},
                    },
                    "newText": "def (",  # syntax error
                }],
            }],
        }
        ok, reason = _check_syntactic_validity(edit)
        assert ok is False
        assert "SyntaxError" in (reason or "")

    def test_non_python_file_skipped(self, tmp_path: Path) -> None:
        f = tmp_path / "x.rs"
        f.write_text("fn main() {}\n")
        edit = {
            "documentChanges": [{
                "textDocument": {"uri": f.as_uri()},
                "edits": [{
                    "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
                    "newText": "invalid rust {{{{",
                }],
            }],
        }
        ok, reason = _check_syntactic_validity(edit)
        assert ok is True  # non-.py skipped

    def test_missing_file_skipped(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.py"
        edit = {
            "documentChanges": [{
                "textDocument": {"uri": missing.as_uri()},
                "edits": [{
                    "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
                    "newText": "hello",
                }],
            }],
        }
        ok, reason = _check_syntactic_validity(edit)
        assert ok is True  # missing file skipped


# ---------------------------------------------------------------------------
# _check_workspace_boundary
# ---------------------------------------------------------------------------


class TestCheckWorkspaceBoundary:
    def test_in_workspace_accepted(self, tmp_path: Path) -> None:
        f = tmp_path / "x.py"
        f.write_text("x = 1\n")
        from serena.refactoring.multi_server import _check_workspace_boundary
        edit = {
            "documentChanges": [{
                "textDocument": {"uri": f.as_uri()},
                "edits": [],
            }],
        }
        ok, reason = _check_workspace_boundary(edit, [str(tmp_path)])
        assert ok is True

    def test_outside_workspace_rejected(self, tmp_path: Path) -> None:
        import tempfile
        other = Path(tempfile.mkdtemp()) / "x.py"
        other.write_text("x = 1\n")
        from serena.refactoring.multi_server import _check_workspace_boundary
        edit = {
            "documentChanges": [{
                "textDocument": {"uri": other.as_uri()},
                "edits": [],
            }],
        }
        ok, reason = _check_workspace_boundary(edit, [str(tmp_path)])
        assert ok is False
        assert "OUT_OF_WORKSPACE" in (reason or "")

    def test_empty_edit_accepted(self, tmp_path: Path) -> None:
        from serena.refactoring.multi_server import _check_workspace_boundary
        ok, reason = _check_workspace_boundary({}, [str(tmp_path)])
        assert ok is True

    def test_extra_paths_accepted(self, tmp_path: Path) -> None:
        f = tmp_path / "x.py"
        f.write_text("")
        from serena.refactoring.multi_server import _check_workspace_boundary
        other_workspace = str(tmp_path.parent)
        edit = {
            "documentChanges": [{
                "textDocument": {"uri": f.as_uri()},
                "edits": [],
            }],
        }
        ok, reason = _check_workspace_boundary(edit, ["/nonexistent"], extra_paths=(str(tmp_path),))
        assert ok is True


# ---------------------------------------------------------------------------
# _reconcile_rename_edits
# ---------------------------------------------------------------------------


class TestReconcileRenameEdits:
    def test_surgical_edit_passes_through(self) -> None:
        """Single-line edit is surgical — passes through unchanged."""
        edit = {
            "documentChanges": [{
                "textDocument": {"uri": "file:///foo.py"},
                "edits": [{
                    "range": {
                        "start": {"line": 3, "character": 4},
                        "end": {"line": 3, "character": 10},
                    },
                    "newText": "new_name",
                }],
            }],
        }
        result = _reconcile_rename_edits(edit, source_reader=lambda uri: "")
        assert len(result) == 1
        uri, te = result[0]
        assert uri == "file:///foo.py"
        assert te["newText"] == "new_name"

    def test_whole_file_edit_falls_back_on_read_error(self) -> None:
        """Whole-file edit falls back to verbatim when source_reader raises."""
        edit = {
            "documentChanges": [{
                "textDocument": {"uri": "file:///missing.py"},
                "edits": [{
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 100, "character": 0},
                    },
                    "newText": "new content\n",
                }],
            }],
        }
        def _raise(uri: str) -> str:
            raise FileNotFoundError("not found")
        result = _reconcile_rename_edits(edit, source_reader=_raise)
        assert len(result) == 1

    def test_skips_non_text_document_changes(self) -> None:
        """File-level ops (create/rename/delete) are skipped."""
        edit = {
            "documentChanges": [
                {"kind": "create", "uri": "file:///new.py"},
            ],
        }
        result = _reconcile_rename_edits(edit, source_reader=lambda uri: "")
        assert result == []


# ---------------------------------------------------------------------------
# _line_hunks
# ---------------------------------------------------------------------------


class TestLineHunks:
    def test_identical_lines_produce_no_hunks(self) -> None:
        lines = ["line1\n", "line2\n"]
        result = _line_hunks(lines, lines)
        assert result == []

    def test_replace_one_line(self) -> None:
        old = ["hello\n", "world\n"]
        new = ["hello\n", "earth\n"]
        result = _line_hunks(old, new)
        assert len(result) == 1
        assert result[0]["newText"] == "earth\n"

    def test_add_line(self) -> None:
        old = ["line1\n"]
        new = ["line1\n", "line2\n"]
        result = _line_hunks(old, new)
        assert len(result) == 1
        assert "line2" in result[0]["newText"]

    def test_delete_line(self) -> None:
        old = ["line1\n", "line2\n"]
        new = ["line1\n"]
        result = _line_hunks(old, new)
        assert len(result) == 1
        assert result[0]["newText"] == ""


# ---------------------------------------------------------------------------
# _rename_symdiff
# ---------------------------------------------------------------------------


class TestRenameSymdiff:
    def test_identical_edits_no_diff(self) -> None:
        edit = {
            "documentChanges": [{
                "textDocument": {"uri": "file:///foo.py"},
                "edits": [{
                    "range": {"start": {"line": 1, "character": 4}, "end": {"line": 1, "character": 8}},
                    "newText": "new_name",
                }],
            }],
        }
        result = _rename_symdiff(edit, edit, source_reader=lambda uri: "")
        assert result["only_in_winner"] == 0
        assert result["only_in_loser"] == 0

    def test_different_edits_produces_symdiff(self) -> None:
        winner = {
            "documentChanges": [{
                "textDocument": {"uri": "file:///foo.py"},
                "edits": [{"range": {"start": {"line": 1, "character": 0}, "end": {"line": 1, "character": 3}}, "newText": "alpha"}],
            }],
        }
        loser = {
            "documentChanges": [{
                "textDocument": {"uri": "file:///foo.py"},
                "edits": [{"range": {"start": {"line": 1, "character": 0}, "end": {"line": 1, "character": 3}}, "newText": "beta"}],
            }],
        }
        result = _rename_symdiff(winner, loser, source_reader=lambda uri: "")
        assert result["only_in_winner"] >= 1
        assert result["only_in_loser"] >= 1


# ---------------------------------------------------------------------------
# _split_name_path + _to_relative_path
# ---------------------------------------------------------------------------


class TestSplitNamePath:
    def test_empty(self) -> None:
        assert _split_name_path("") == []

    def test_single_segment(self) -> None:
        assert _split_name_path("foo") == ["foo"]

    def test_dotted_python(self) -> None:
        assert _split_name_path("module.Class.method") == ["module", "Class", "method"]

    def test_double_colon_rust(self) -> None:
        assert _split_name_path("crate::module::fn") == ["crate", "module", "fn"]

    def test_mixed(self) -> None:
        assert _split_name_path("outer::inner.method") == ["outer", "inner", "method"]

    def test_leading_trailing_dots(self) -> None:
        # Empty pieces are filtered.
        result = _split_name_path("::foo::")
        assert "foo" in result


class TestToRelativePath:
    def test_absolute_path_no_root(self) -> None:
        result = _to_relative_path("/some/path/file.py", None)
        assert result == "/some/path/file.py"

    def test_relative_to_root(self, tmp_path: Path) -> None:
        f = tmp_path / "src" / "module.py"
        result = _to_relative_path(str(f), str(tmp_path))
        assert "src" in result
        assert str(tmp_path) not in result

    def test_outside_root_returns_original(self, tmp_path: Path) -> None:
        f = "/completely/other/path/file.py"
        result = _to_relative_path(f, str(tmp_path))
        assert result == f


# ---------------------------------------------------------------------------
# _walk_document_symbols_for_range
# ---------------------------------------------------------------------------


class TestWalkDocumentSymbolsForRange:
    def _sym(self, name: str, line: int, end_line: int, children: list | None = None) -> dict:
        return {
            "name": name,
            "range": {
                "start": {"line": line, "character": 0},
                "end": {"line": end_line, "character": 0},
            },
            "selectionRange": {
                "start": {"line": line, "character": 0},
                "end": {"line": line, "character": len(name)},
            },
            "children": children or [],
        }

    def test_top_level_match(self) -> None:
        nodes = [self._sym("alpha", 0, 5), self._sym("beta", 6, 10)]
        result = _walk_document_symbols_for_range(nodes, ["alpha"])
        assert result is not None
        assert result["start"]["line"] == 0
        assert result["end"]["line"] == 5

    def test_nested_match(self) -> None:
        inner = self._sym("method", 3, 7)
        outer = self._sym("MyClass", 1, 10, children=[inner])
        result = _walk_document_symbols_for_range([outer], ["MyClass", "method"])
        assert result is not None
        assert result["start"]["line"] == 3

    def test_no_match_returns_none(self) -> None:
        nodes = [self._sym("alpha", 0, 5)]
        result = _walk_document_symbols_for_range(nodes, ["missing"])
        assert result is None

    def test_empty_segments_returns_none(self) -> None:
        nodes = [self._sym("alpha", 0, 5)]
        result = _walk_document_symbols_for_range(nodes, [])
        assert result is None

    def test_fallback_to_selection_range(self) -> None:
        node = {
            "name": "foo",
            "selectionRange": {
                "start": {"line": 2, "character": 0},
                "end": {"line": 2, "character": 3},
            },
            # No "range" key
            "children": [],
        }
        result = _walk_document_symbols_for_range([node], ["foo"])
        assert result is not None
        assert result["start"]["line"] == 2

    def test_non_dict_node_skipped(self) -> None:
        nodes = ["not a dict", self._sym("foo", 0, 1)]
        result = _walk_document_symbols_for_range(nodes, ["foo"])
        assert result is not None


# ---------------------------------------------------------------------------
# MultiServerCoordinator.broadcast (async)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMultiServerBroadcast:
    async def test_broadcast_collects_responses(self) -> None:
        server1 = _make_async_server("pylsp-rope")
        server2 = _make_async_server("ruff")

        async def _code_actions(**kwargs: Any) -> list:
            return [{"title": f"from {kwargs}"}]

        server1.request_code_actions.side_effect = _code_actions
        server2.request_code_actions.side_effect = _code_actions
        server1.request_code_actions._o2_async_callable = True
        server2.request_code_actions._o2_async_callable = True

        coord = _make_coord({"pylsp-rope": server1, "ruff": server2})
        result = await coord.broadcast(
            method="textDocument/codeAction",
            kwargs={"file": "/tmp/x.py", "start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
        )
        assert "pylsp-rope" in result.responses
        assert "ruff" in result.responses

    async def test_broadcast_unsupported_method_raises(self) -> None:
        server1 = _make_async_server("pylsp-rope")
        coord = _make_coord({"pylsp-rope": server1})
        with pytest.raises(ValueError, match="unsupported broadcast method"):
            await coord.broadcast(method="textDocument/definition", kwargs={})

    async def test_broadcast_timeout_captured(self) -> None:
        server1 = _make_async_server("pylsp-rope")

        async def _slow(**kwargs: Any) -> list:
            await asyncio.sleep(10.0)
            return []

        server1.request_code_actions.side_effect = _slow
        server1.request_code_actions._o2_async_callable = True

        coord = _make_coord({"pylsp-rope": server1})
        result = await coord.broadcast(
            method="textDocument/codeAction",
            kwargs={"file": "/tmp/x.py", "start": {}, "end": {}},
            timeout_ms=1,  # 1ms → will timeout
        )
        assert len(result.timeouts) == 1
        assert result.timeouts[0].server == "pylsp-rope"

    async def test_broadcast_error_captured(self) -> None:
        server1 = _make_async_server("pylsp-rope")

        async def _raise(**kwargs: Any) -> list:
            raise RuntimeError("server error")

        server1.request_code_actions.side_effect = _raise
        server1.request_code_actions._o2_async_callable = True

        coord = _make_coord({"pylsp-rope": server1})
        result = await coord.broadcast(
            method="textDocument/codeAction",
            kwargs={"file": "/tmp/x.py", "start": {}, "end": {}},
        )
        assert "pylsp-rope" in result.errors
        assert "RuntimeError" in result.errors["pylsp-rope"]


# ---------------------------------------------------------------------------
# MultiServerCoordinator._resolve_if_needed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestResolveIfNeeded:
    async def test_action_with_edit_returned_directly(self) -> None:
        server = _make_async_server("pylsp-rope")
        coord = _make_coord({"pylsp-rope": server})
        action = {"edit": {"documentChanges": []}}
        result = await coord._resolve_if_needed("pylsp-rope", action)
        assert result is action
        server.resolve_code_action.assert_not_called()

    async def test_action_with_command_returned_directly(self) -> None:
        server = _make_async_server("pylsp-rope")
        coord = _make_coord({"pylsp-rope": server})
        action = {"command": {"command": "pylsp.doSomething"}}
        result = await coord._resolve_if_needed("pylsp-rope", action)
        assert result is action

    async def test_no_edit_no_command_triggers_resolve(self) -> None:
        server = _make_async_server("pylsp-rope")
        resolved = {"edit": {"documentChanges": []}, "title": "resolved"}

        async def _resolve(action: dict) -> dict:
            return resolved

        server.resolve_code_action.side_effect = _resolve
        server.resolve_code_action._o2_async_callable = True

        coord = _make_coord({"pylsp-rope": server})
        action = {"title": "unresolved"}
        result = await coord._resolve_if_needed("pylsp-rope", action)
        assert result == resolved

    async def test_resolve_failure_returns_original(self) -> None:
        server = _make_async_server("pylsp-rope")

        async def _raise(action: dict) -> dict:
            raise RuntimeError("resolve failed")

        server.resolve_code_action.side_effect = _raise
        server.resolve_code_action._o2_async_callable = True

        coord = _make_coord({"pylsp-rope": server})
        action = {"title": "unresolved"}
        result = await coord._resolve_if_needed("pylsp-rope", action)
        assert result is action  # returned as-is


# ---------------------------------------------------------------------------
# MultiServerCoordinator.merge_code_actions (full async path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMergeCodeActions:
    async def test_basic_merge_from_single_server(self) -> None:
        server = _make_async_server("ruff")

        async def _actions(**kwargs: Any) -> list:
            return [
                {"title": "organize imports", "kind": "source.organizeImports", "isPreferred": True},
            ]

        server.request_code_actions.side_effect = _actions
        server.request_code_actions._o2_async_callable = True

        coord = _make_coord({"ruff": server})
        merged = await coord.merge_code_actions(
            file="/tmp/x.py",
            start={"line": 0, "character": 0},
            end={"line": 0, "character": 0},
        )
        assert len(merged) == 1
        assert merged[0].title == "organize imports"
        assert merged[0].provenance == "ruff"

    async def test_merge_two_servers_priority_applied(self) -> None:
        server_ruff = _make_async_server("ruff")
        server_pylsp = _make_async_server("pylsp-rope")

        async def _ruff_actions(**kwargs: Any) -> list:
            return [{"title": "fix all", "kind": "source.fixAll"}]

        async def _pylsp_actions(**kwargs: Any) -> list:
            return [{"title": "fix all", "kind": "source.fixAll"}]

        server_ruff.request_code_actions.side_effect = _ruff_actions
        server_ruff.request_code_actions._o2_async_callable = True
        server_pylsp.request_code_actions.side_effect = _pylsp_actions
        server_pylsp.request_code_actions._o2_async_callable = True

        coord = _make_coord({"ruff": server_ruff, "pylsp-rope": server_pylsp})
        merged = await coord.merge_code_actions(
            file="/tmp/x.py",
            start={"line": 0, "character": 0},
            end={"line": 0, "character": 0},
        )
        # Both have "source.fixAll"; ruff wins per priority table.
        assert any(m.provenance == "ruff" for m in merged)

    async def test_disabled_action_surfaced(self) -> None:
        server = _make_async_server("basedpyright")

        async def _actions(**kwargs: Any) -> list:
            return [{"title": "disabled", "kind": "quickfix", "disabled": {"reason": "not available"}}]

        server.request_code_actions.side_effect = _actions
        server.request_code_actions._o2_async_callable = True

        coord = _make_coord({"basedpyright": server})
        merged = await coord.merge_code_actions(
            file="/tmp/x.py",
            start={"line": 0, "character": 0},
            end={"line": 0, "character": 0},
        )
        assert len(merged) == 1
        assert merged[0].disabled_reason == "not available"

    async def test_action_edit_stored(self) -> None:
        server = _make_async_server("ruff")
        edit = {"documentChanges": [{"textDocument": {"uri": "file:///x.py"}, "edits": []}]}

        async def _actions(**kwargs: Any) -> list:
            return [{"title": "fix", "kind": "source.fixAll", "edit": edit, "data": {"id": "action-1"}}]

        server.request_code_actions.side_effect = _actions
        server.request_code_actions._o2_async_callable = True

        coord = _make_coord({"ruff": server})
        merged = await coord.merge_code_actions(
            file="/tmp/x.py",
            start={"line": 0, "character": 0},
            end={"line": 0, "character": 0},
        )
        assert coord.get_action_edit("action-1") == edit

    async def test_get_action_edit_missing_returns_none(self) -> None:
        server = _make_async_server("ruff")
        coord = _make_coord({"ruff": server})
        assert coord.get_action_edit("nonexistent") is None

    async def test_debug_merge_suppressed_alternatives(self) -> None:
        server_ruff = _make_async_server("ruff")
        server_pylsp = _make_async_server("pylsp-rope")

        async def _actions(**kwargs: Any) -> list:
            return [{"title": "fix imports", "kind": "source.organizeImports"}]

        server_ruff.request_code_actions.side_effect = _actions
        server_ruff.request_code_actions._o2_async_callable = True
        server_pylsp.request_code_actions.side_effect = _actions
        server_pylsp.request_code_actions._o2_async_callable = True

        coord = _make_coord({"ruff": server_ruff, "pylsp-rope": server_pylsp})
        with patch.dict(os.environ, {"O2_SCALPEL_DEBUG_MERGE": "1"}):
            merged = await coord.merge_code_actions(
                file="/tmp/x.py",
                start={"line": 0, "character": 0},
                end={"line": 0, "character": 0},
            )
        # In debug mode, suppressed_alternatives populated.
        winner = merged[0]
        assert winner.provenance == "ruff"  # ruff wins source.organizeImports
        assert len(winner.suppressed_alternatives) >= 1

    async def test_unknown_provenance_falls_back_to_pylsp_base(self) -> None:
        server = _make_async_server("unknown-server")

        async def _actions(**kwargs: Any) -> list:
            return [{"title": "action", "kind": "refactor"}]

        server.request_code_actions.side_effect = _actions
        server.request_code_actions._o2_async_callable = True

        coord = _make_coord({"unknown-server": server})
        merged = await coord.merge_code_actions(
            file="/tmp/x.py",
            start={"line": 0, "character": 0},
            end={"line": 0, "character": 0},
        )
        assert len(merged) == 1
        assert merged[0].provenance == "pylsp-base"

    async def test_arguments_forwarded(self) -> None:
        """v1.5 G4-6: 'arguments' kwarg forwarded when provided."""
        server = _make_async_server("pylsp-rope")
        received_kwargs: list = []

        async def _actions(**kwargs: Any) -> list:
            received_kwargs.append(dict(kwargs))
            return []

        server.request_code_actions.side_effect = _actions
        server.request_code_actions._o2_async_callable = True

        coord = _make_coord({"pylsp-rope": server})
        await coord.merge_code_actions(
            file="/tmp/x.py",
            start={"line": 0, "character": 0},
            end={"line": 0, "character": 0},
            arguments=[{"similar": True}],
        )
        # The broadcast_kwargs should include 'arguments'.
        assert any("arguments" in kw for kw in received_kwargs)


# ---------------------------------------------------------------------------
# MultiServerCoordinator.merge_rename
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMergeRename:
    async def test_no_primary_server_returns_none(self) -> None:
        # Only ruff in pool — no rename primary for python (pylsp-rope absent).
        server = _make_async_server("ruff")
        coord = _make_coord({"ruff": server})
        result, warnings = await coord.merge_rename(
            relative_file_path="x.py", line=5, column=4, new_name="new_name",
        )
        assert result is None
        assert warnings == []

    async def test_primary_returns_none_result_is_none(self) -> None:
        server = _make_async_server("pylsp-rope")

        async def _rename(**kwargs: Any) -> None:
            return None

        server.request_rename_symbol_edit.side_effect = _rename
        server.request_rename_symbol_edit._o2_async_callable = True

        coord = _make_coord({"pylsp-rope": server})
        result, warnings = await coord.merge_rename(
            relative_file_path="x.py", line=5, column=4, new_name="new_name",
        )
        assert result is None
        assert warnings == []

    async def test_primary_returns_edit(self) -> None:
        server = _make_async_server("pylsp-rope")
        workspace_edit = {"documentChanges": []}

        async def _rename(**kwargs: Any) -> dict:
            return workspace_edit

        server.request_rename_symbol_edit.side_effect = _rename
        server.request_rename_symbol_edit._o2_async_callable = True

        coord = _make_coord({"pylsp-rope": server})
        result, warnings = await coord.merge_rename(
            relative_file_path="x.py", line=5, column=4, new_name="new_name",
        )
        assert result == workspace_edit
        assert warnings == []

    async def test_debug_merge_secondary_loser_none(self) -> None:
        primary_server = _make_async_server("pylsp-rope")
        secondary_server = _make_async_server("basedpyright")
        workspace_edit = {"documentChanges": []}

        async def _primary_rename(**kwargs: Any) -> dict:
            return workspace_edit

        async def _secondary_rename(**kwargs: Any) -> None:
            return None

        primary_server.request_rename_symbol_edit.side_effect = _primary_rename
        primary_server.request_rename_symbol_edit._o2_async_callable = True
        secondary_server.request_rename_symbol_edit.side_effect = _secondary_rename
        secondary_server.request_rename_symbol_edit._o2_async_callable = True

        coord = _make_coord({"pylsp-rope": primary_server, "basedpyright": secondary_server})
        with patch.dict(os.environ, {"O2_SCALPEL_DEBUG_MERGE": "1"}):
            result, warnings = await coord.merge_rename(
                relative_file_path="x.py", line=5, column=4, new_name="new_name",
            )
        assert result == workspace_edit
        assert any(w.get("loser_returned_none") for w in warnings)

    async def test_debug_merge_secondary_loser_error(self) -> None:
        primary_server = _make_async_server("pylsp-rope")
        secondary_server = _make_async_server("basedpyright")
        workspace_edit = {"documentChanges": []}

        async def _primary_rename(**kwargs: Any) -> dict:
            return workspace_edit

        async def _secondary_rename(**kwargs: Any) -> dict:
            raise RuntimeError("secondary server error")

        primary_server.request_rename_symbol_edit.side_effect = _primary_rename
        primary_server.request_rename_symbol_edit._o2_async_callable = True
        secondary_server.request_rename_symbol_edit.side_effect = _secondary_rename
        secondary_server.request_rename_symbol_edit._o2_async_callable = True

        coord = _make_coord({"pylsp-rope": primary_server, "basedpyright": secondary_server})
        with patch.dict(os.environ, {"O2_SCALPEL_DEBUG_MERGE": "1"}):
            result, warnings = await coord.merge_rename(
                relative_file_path="x.py", line=5, column=4, new_name="new_name",
            )
        assert result == workspace_edit
        assert any("loser_error" in w for w in warnings)

    async def test_debug_merge_both_present_symdiff_warning(self) -> None:
        primary_server = _make_async_server("pylsp-rope")
        secondary_server = _make_async_server("basedpyright")
        edit_a = {"documentChanges": [{"textDocument": {"uri": "file:///a.py"}, "edits": [{"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 3}}, "newText": "alpha"}]}]}
        edit_b = {"documentChanges": [{"textDocument": {"uri": "file:///a.py"}, "edits": [{"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 3}}, "newText": "beta"}]}]}

        async def _primary_rename(**kwargs: Any) -> dict:
            return edit_a

        async def _secondary_rename(**kwargs: Any) -> dict:
            return edit_b

        primary_server.request_rename_symbol_edit.side_effect = _primary_rename
        primary_server.request_rename_symbol_edit._o2_async_callable = True
        secondary_server.request_rename_symbol_edit.side_effect = _secondary_rename
        secondary_server.request_rename_symbol_edit._o2_async_callable = True

        coord = _make_coord({"pylsp-rope": primary_server, "basedpyright": secondary_server})
        with patch.dict(os.environ, {"O2_SCALPEL_DEBUG_MERGE": "1"}):
            result, warnings = await coord.merge_rename(
                relative_file_path="x.py", line=5, column=4, new_name="new_name",
            )
        assert result == edit_a
        assert any("symdiff" in w for w in warnings)


# ---------------------------------------------------------------------------
# MultiServerCoordinator.expand_macro / fetch_runnables / run_flycheck
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCoordinatorRustExtensions:
    async def test_expand_macro_no_ra_server(self) -> None:
        server = _make_async_server("pylsp-rope")
        coord = _make_coord({"pylsp-rope": server})
        result = await coord.expand_macro(file="/tmp/x.rs", position={"line": 0, "character": 0})
        assert result is None

    async def test_expand_macro_no_method(self) -> None:
        server = _make_async_server("rust-analyzer")
        del server.expand_macro  # remove attribute entirely
        coord = _make_coord({"rust-analyzer": server})
        result = await coord.expand_macro(file="/tmp/x.rs", position={"line": 0, "character": 0})
        assert result is None

    async def test_expand_macro_returns_dict(self) -> None:
        server = _make_async_server("rust-analyzer")
        server.expand_macro = MagicMock(return_value={"name": "my_macro", "expansion": "x + y"})
        coord = _make_coord({"rust-analyzer": server})
        result = await coord.expand_macro(file="/tmp/x.rs", position={"line": 0, "character": 0})
        assert result == {"name": "my_macro", "expansion": "x + y"}

    async def test_expand_macro_non_dict_returns_none(self) -> None:
        server = _make_async_server("rust-analyzer")
        server.expand_macro = MagicMock(return_value="not a dict")
        coord = _make_coord({"rust-analyzer": server})
        result = await coord.expand_macro(file="/tmp/x.rs", position={"line": 0, "character": 0})
        assert result is None

    async def test_fetch_runnables_no_ra_server(self) -> None:
        server = _make_async_server("pylsp-rope")
        coord = _make_coord({"pylsp-rope": server})
        result = await coord.fetch_runnables(file="/tmp/x.rs")
        assert result == []

    async def test_fetch_runnables_no_method(self) -> None:
        server = _make_async_server("rust-analyzer")
        del server.fetch_runnables
        coord = _make_coord({"rust-analyzer": server})
        result = await coord.fetch_runnables(file="/tmp/x.rs")
        assert result == []

    async def test_fetch_runnables_returns_list(self) -> None:
        server = _make_async_server("rust-analyzer")
        server.fetch_runnables = MagicMock(return_value=[{"label": "run test"}])
        coord = _make_coord({"rust-analyzer": server})
        result = await coord.fetch_runnables(file="/tmp/x.rs")
        assert result == [{"label": "run test"}]

    async def test_fetch_runnables_non_list_returns_empty(self) -> None:
        server = _make_async_server("rust-analyzer")
        server.fetch_runnables = MagicMock(return_value="not a list")
        coord = _make_coord({"rust-analyzer": server})
        result = await coord.fetch_runnables(file="/tmp/x.rs")
        assert result == []

    async def test_run_flycheck_no_ra_server(self) -> None:
        server = _make_async_server("pylsp-rope")
        coord = _make_coord({"pylsp-rope": server})
        result = await coord.run_flycheck(file="/tmp/x.rs")
        assert result == {"diagnostics": []}

    async def test_run_flycheck_no_method(self) -> None:
        server = _make_async_server("rust-analyzer")
        del server.run_flycheck
        coord = _make_coord({"rust-analyzer": server})
        result = await coord.run_flycheck(file="/tmp/x.rs")
        assert result == {"diagnostics": []}

    async def test_run_flycheck_returns_dict(self) -> None:
        server = _make_async_server("rust-analyzer")
        server.run_flycheck = MagicMock(return_value={"diagnostics": [{"message": "unused"}]})
        coord = _make_coord({"rust-analyzer": server})
        result = await coord.run_flycheck(file="/tmp/x.rs")
        assert result == {"diagnostics": [{"message": "unused"}]}

    async def test_run_flycheck_non_dict_returns_empty(self) -> None:
        server = _make_async_server("rust-analyzer")
        server.run_flycheck = MagicMock(return_value="not a dict")
        coord = _make_coord({"rust-analyzer": server})
        result = await coord.run_flycheck(file="/tmp/x.rs")
        assert result == {"diagnostics": []}


# ---------------------------------------------------------------------------
# EditAttributionLog
# ---------------------------------------------------------------------------


class TestEditAttributionLog:
    def test_path_property(self, tmp_path: Path) -> None:
        log = EditAttributionLog(tmp_path)
        assert log.path == tmp_path / ".serena" / "python-edit-log.jsonl"

    @pytest.mark.asyncio
    async def test_append_text_document_edit(self, tmp_path: Path) -> None:
        log = EditAttributionLog(tmp_path)
        edit = {
            "documentChanges": [{
                "textDocument": {"uri": "file:///x.py", "version": 1},
                "edits": [
                    {"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 3}}, "newText": "new"},
                ],
            }],
        }
        await log.append(
            checkpoint_id="ckpt-1",
            tool="scalpel_rename",
            server="pylsp-rope",
            edit=edit,
        )
        records = list(log.replay())
        assert len(records) == 1
        rec = records[0]
        assert rec["tool"] == "scalpel_rename"
        assert rec["server"] == "pylsp-rope"
        assert rec["checkpoint_id"] == "ckpt-1"
        assert rec["kind"] == "TextDocumentEdit"
        assert rec["edit_count"] == 1

    @pytest.mark.asyncio
    async def test_append_create_file(self, tmp_path: Path) -> None:
        log = EditAttributionLog(tmp_path)
        edit = {
            "documentChanges": [{"kind": "create", "uri": "file:///new.py"}],
        }
        await log.append(checkpoint_id="ckpt-2", tool="tool", server="srv", edit=edit)
        records = list(log.replay())
        assert records[0]["kind"] == "CreateFile"

    @pytest.mark.asyncio
    async def test_append_rename_file(self, tmp_path: Path) -> None:
        log = EditAttributionLog(tmp_path)
        edit = {
            "documentChanges": [{"kind": "rename", "oldUri": "file:///old.py", "newUri": "file:///new.py"}],
        }
        await log.append(checkpoint_id="ckpt-3", tool="tool", server="srv", edit=edit)
        records = list(log.replay())
        assert records[0]["kind"] == "RenameFile"
        assert records[0]["uri"] == "file:///new.py"

    @pytest.mark.asyncio
    async def test_append_delete_file(self, tmp_path: Path) -> None:
        log = EditAttributionLog(tmp_path)
        edit = {
            "documentChanges": [{"kind": "delete", "uri": "file:///old.py"}],
        }
        await log.append(checkpoint_id="ckpt-4", tool="tool", server="srv", edit=edit)
        records = list(log.replay())
        assert records[0]["kind"] == "DeleteFile"

    @pytest.mark.asyncio
    async def test_append_empty_edit_no_records(self, tmp_path: Path) -> None:
        log = EditAttributionLog(tmp_path)
        await log.append(checkpoint_id="c", tool="t", server="s", edit={})
        records = list(log.replay())
        assert records == []

    def test_replay_missing_log_returns_empty(self, tmp_path: Path) -> None:
        log = EditAttributionLog(tmp_path)
        records = list(log.replay())
        assert records == []

    @pytest.mark.asyncio
    async def test_append_multiple_appends(self, tmp_path: Path) -> None:
        log = EditAttributionLog(tmp_path)
        edit = {
            "documentChanges": [
                {"textDocument": {"uri": "file:///a.py", "version": None}, "edits": []},
                {"textDocument": {"uri": "file:///b.py", "version": None}, "edits": []},
            ],
        }
        await log.append(checkpoint_id="c1", tool="t1", server="s1", edit=edit)
        await log.append(checkpoint_id="c2", tool="t2", server="s2", edit=edit)
        records = list(log.replay())
        assert len(records) == 4  # 2 files × 2 appends


# ---------------------------------------------------------------------------
# MultiServerCoordinator.supports_method
# ---------------------------------------------------------------------------


class TestSupportsMethod:
    def test_returns_false_for_absent_server(self) -> None:
        server = _make_async_server("pylsp-rope")
        coord = _make_coord({"pylsp-rope": server})
        assert coord.supports_method("nonexistent", "textDocument/rename") is False

    def test_server_without_server_capabilities(self) -> None:
        server = _make_async_server("pylsp-rope")
        del server.server_capabilities  # remove callable
        coord = _make_coord({"pylsp-rope": server})
        # Unknown method → False
        assert coord.supports_method("pylsp-rope", "textDocument/foobar") is False

    def test_prepare_rename_requires_prepare_provider_true(self) -> None:
        from solidlsp.capability_keys import PREPARE_RENAME
        server = _make_async_server("pylsp-rope")
        server.server_capabilities.return_value = {
            "renameProvider": {"prepareProvider": True},
        }
        coord = _make_coord({"pylsp-rope": server})
        assert coord.supports_method("pylsp-rope", PREPARE_RENAME) is True

    def test_prepare_rename_bare_bool_is_false(self) -> None:
        from solidlsp.capability_keys import PREPARE_RENAME
        server = _make_async_server("pylsp-rope")
        server.server_capabilities.return_value = {"renameProvider": True}
        coord = _make_coord({"pylsp-rope": server})
        assert coord.supports_method("pylsp-rope", PREPARE_RENAME) is False

    def test_dynamic_registry_overrides(self) -> None:
        server = _make_async_server("pylsp-rope")
        server.server_capabilities.return_value = {}
        registry = DynamicCapabilityRegistry()
        registry.register("pylsp-rope", "reg-1", "textDocument/rename", {})
        coord = MultiServerCoordinator(
            servers={"pylsp-rope": server},
            dynamic_registry=registry,
            catalog=None,
        )
        assert coord.supports_method("pylsp-rope", "textDocument/rename") is True
