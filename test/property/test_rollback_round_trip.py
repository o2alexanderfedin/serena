"""
B3 — Rollback inverse-applier round-trip property.

regression: docs/superpowers/specs/2026-05-03-test-coverage-strategy-design.md §6 Phase B B3
regression: v1.7-p7-rollback-inverse-applier (parent d0a7a75d)

Property: apply(edit) ; apply(inverse_workspace_edit(edit, pre_snapshot))
restores file bytes to the pre-apply state. Pre-v1.7, rollback was a
no-op disguised as success; this property would have caught it.

Design notes:
- snapshot keys are URIs (str) and values are str (not bytes) — per
  inverse_workspace_edit's type signature: dict[str, str].
- The initial WorkspaceEdit is in documentChanges format (array shape)
  so that inverse_workspace_edit can inspect change.get("kind") correctly.
- The inverse synthesizer emits a 3-op sequence for TextDocumentEdit:
  delete(ignoreIfNotExists) → create(overwrite) → insert-at-(0,0).
  The insert target is a freshly-created empty file, so the PB7
  zero-width-on-non-empty bug does NOT apply here.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from serena.refactoring.checkpoints import inverse_workspace_edit
from serena.tools.facade_support import _apply_workspace_edit_to_disk

# Strategy: a small ASCII source file's content.
# min_size=1 to ensure there is always at least one character,
# giving the applier a non-trivial edit to apply.
_SAFE_CHARS = st.characters(
    min_codepoint=0x20,
    max_codepoint=0x7E,
    blacklist_characters="\r",  # avoid CR so newlines are consistent
)

file_content_st = st.text(
    alphabet=_SAFE_CHARS,
    min_size=1,
    max_size=200,
).map(lambda s: s if s.endswith("\n") else s + "\n")

replacement_st = st.text(
    alphabet=_SAFE_CHARS,
    min_size=0,
    max_size=80,
)


@given(content=file_content_st, replacement=replacement_st)
@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_rollback_restores_file_content(content: str, replacement: str) -> None:
    """apply(edit) ; apply(inverse) restores file text to pre-apply state."""
    with tempfile.TemporaryDirectory(prefix="phase-b-pb8-") as td:
        src = Path(td) / "src.py"
        src.write_text(content, encoding="utf-8")
        pre_content = src.read_text(encoding="utf-8")

        uri = src.as_uri()

        # Snapshot: URI → string content (pre-apply state).
        # inverse_workspace_edit expects dict[str, str].
        snapshot: dict[str, str] = {uri: pre_content}

        # Build a whole-file replacement using documentChanges shape.
        # inverse_workspace_edit needs this array shape (not the legacy
        # changes dict shape) to infer change kinds correctly.
        lines = content.split("\n")
        last_line = max(0, len(lines) - 1)
        last_col = len(lines[last_line]) if lines else 0

        workspace_edit: dict = {
            "documentChanges": [
                {
                    "textDocument": {"uri": uri, "version": None},
                    "edits": [
                        {
                            "range": {
                                "start": {"line": 0, "character": 0},
                                "end": {"line": last_line, "character": last_col},
                            },
                            "newText": replacement,
                        }
                    ],
                }
            ]
        }

        # Step 1: Apply the edit.
        n_applied = _apply_workspace_edit_to_disk(workspace_edit)
        assert n_applied >= 1, "apply produced no changes"

        # Step 2: Synthesize the inverse.
        inverse = inverse_workspace_edit(applied=workspace_edit, snapshot=snapshot)
        assert inverse and inverse.get("documentChanges"), (
            "inverse_workspace_edit produced an empty edit"
        )

        # Step 3: Apply the inverse (rollback).
        n_inv = _apply_workspace_edit_to_disk(inverse)
        assert n_inv >= 1, (
            "inverse apply produced no changes — rollback would be a no-op "
            "(pre-v1.7 regression)"
        )

        # Step 4: Assert round-trip identity.
        after_rollback = src.read_text(encoding="utf-8")
        assert after_rollback == pre_content, (
            f"Rollback failed to restore file content.\n"
            f"  Pre={pre_content!r}\n"
            f"  Applied edit newText={replacement!r}\n"
            f"  After rollback={after_rollback!r}"
        )
