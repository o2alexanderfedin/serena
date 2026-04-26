"""T10 — §11.2 six disagreement cases (helper-only partial).

This file pins the two pure-function helpers from §11.2 cases 1 + 5:
``_classify_overlap`` (subset_lossless / subset_lossy / disjoint) and
``_bucket_unknown_kind`` (null / unrecognized → ``quickfix.other``).

Cases 2 / 3 / 4 / 6 require a ``MergeCodeActionsResult`` wrapper API
that T6 did not build (T6's ``merge_code_actions`` returns a bare
``list[MergedCodeAction]``). Adding the wrapper would refactor T6 + T7
contracts; T11 e2e exercises those paths via
``MultiServerBroadcastResult.timeouts`` directly. Those four integration
tests are deferred to the Stage 1E facade layer.
"""

from __future__ import annotations

from typing import Any

from serena.refactoring.multi_server import (
    _bucket_unknown_kind,
    _classify_overlap,
)


def _action(title: str, kind: str, edit: dict[str, Any] | None = None,
            disabled: dict[str, str] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"title": title, "kind": kind}
    if edit is not None:
        out["edit"] = edit
    if disabled is not None:
        out["disabled"] = disabled
    return out


def _edit(uri: str, sl: int, sc: int, el: int, ec: int, txt: str) -> dict[str, Any]:
    return {
        "documentChanges": [
            {
                "textDocument": {"uri": uri, "version": None},
                "edits": [
                    {"range": {"start": {"line": sl, "character": sc}, "end": {"line": el, "character": ec}}, "newText": txt}
                ],
            }
        ]
    }


# ---------------------------------------------------------------------------
# Case 1 — overlap (one subset of the other) → pick higher-priority; warn
# only if lower-priority would have produced changes the higher-priority does not.
# ---------------------------------------------------------------------------

def test_overlap_subset_no_extra_changes_no_warning() -> None:
    """Lower-priority is strict subset; nothing lost → no warning."""
    higher = _edit("file:///x.py", 0, 0, 0, 10, "ALPHA-BETA")
    lower = _edit("file:///x.py", 0, 0, 0, 5, "ALPHA")
    classification = _classify_overlap(higher, lower)
    assert classification == "subset_lossless"


def test_overlap_lower_priority_changes_more_emits_warning() -> None:
    """Lower-priority touches a byte range higher-priority does not → warn."""
    higher = _edit("file:///x.py", 0, 0, 0, 5, "ALPHA")
    lower = {
        "documentChanges": [
            {"textDocument": {"uri": "file:///x.py", "version": None},
             "edits": [
                 {"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 5}}, "newText": "ALPHA"},
                 {"range": {"start": {"line": 5, "character": 0}, "end": {"line": 5, "character": 8}}, "newText": "EXTRA"},
             ]}
        ]
    }
    classification = _classify_overlap(higher, lower)
    assert classification == "subset_lossy"


# ---------------------------------------------------------------------------
# Case 5 — kind: null or unrecognized → bucketed as quickfix.other (lowest).
# ---------------------------------------------------------------------------

def test_bucket_unknown_kind_maps_null_to_quickfix_other() -> None:
    assert _bucket_unknown_kind(None) == "quickfix.other"
    assert _bucket_unknown_kind("") == "quickfix.other"


def test_bucket_unknown_kind_maps_unrecognized_prefix_to_quickfix_other() -> None:
    assert _bucket_unknown_kind("vendor.experimental.foo") == "quickfix.other"


def test_bucket_unknown_kind_passes_through_known_prefix() -> None:
    assert _bucket_unknown_kind("source.organizeImports") == "source.organizeImports"
    assert _bucket_unknown_kind("refactor.extract") == "refactor.extract"
    assert _bucket_unknown_kind("quickfix") == "quickfix"
