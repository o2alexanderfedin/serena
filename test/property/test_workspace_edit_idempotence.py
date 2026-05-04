"""
B4 — WorkspaceEdit applier idempotence (pure-python disk applier).

regression: docs/superpowers/specs/2026-05-03-test-coverage-strategy-design.md §6 Phase B B4
regression: v0.3.0-facade-application-complete (parent 2026-04-26)

Property: applying the same WorkspaceEdit twice via
``_apply_workspace_edit_to_disk`` produces the same final disk state
as applying it once. The first apply changes bytes; the second apply
must leave the disk unchanged from after-first-apply state.

Known bug (B4-BUG-01)
---------------------
The applier is NOT idempotent for zero-width insertions (start == end).
Minimal reproducer::

    file_content = ''
    edit = range(0,0)..(0,0) -> '0'
    after first apply  -> b'0'
    after second apply -> b'00'   # doubled

Root cause: ``_apply_text_edits_to_file_uri`` re-reads the already-mutated
file and re-splices ``newText`` at the *same* LSP position, which for a
pure insertion (no range to consume) simply inserts again.

The test is marked ``xfail(strict=True)`` so it surfaces as XFAIL in CI
(bug is known and documented) rather than as a hard FAIL.  Once the
applier is made idempotent for insertions the ``xfail`` should be removed.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from serena.tools.facade_support import _apply_workspace_edit_to_disk


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Small ASCII source content with a trailing newline.
_file_content_st = st.text(
    alphabet=st.characters(
        min_codepoint=0x20,
        max_codepoint=0x7E,
        blacklist_characters="\r",
    ),
    min_size=0,
    max_size=300,
).map(lambda s: s + "\n" if s and not s.endswith("\n") else s)


def _edit_st(content: str) -> st.SearchStrategy[tuple[int, int, int, int, str]]:
    """Return a strategy for a single valid TextEdit over ``content``."""
    lines = content.split("\n") if content else [""]
    last_line = max(0, len(lines) - 1)

    @st.composite
    def _build(draw: st.DrawFn) -> tuple[int, int, int, int, str]:
        sl = draw(st.integers(min_value=0, max_value=last_line))
        el = draw(st.integers(min_value=sl, max_value=last_line))
        max_sc = len(lines[sl]) if sl < len(lines) else 0
        max_ec = len(lines[el]) if el < len(lines) else 0
        sc = draw(st.integers(min_value=0, max_value=max_sc))
        # end col must be >= start col when on the same line
        ec = draw(st.integers(min_value=(sc if el == sl else 0), max_value=max_ec))
        new_text = draw(st.text(min_size=0, max_size=40))
        return sl, sc, el, ec, new_text

    return _build()


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "B4-BUG-01: _apply_workspace_edit_to_disk is not idempotent for "
        "zero-width insertions (start==end, newText non-empty). "
        "Minimal: file='', edit=range(0,0)..(0,0)->'0' -> b'0' then b'00'. "
        "Remove xfail once applier guards against re-inserting on second call."
    ),
)
@given(_file_content_st, st.data())
@settings(
    max_examples=30,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_apply_workspace_edit_to_disk_is_idempotent(
    file_content: str,
    data: st.DataObject,
) -> None:
    """Apply the same WorkspaceEdit twice; disk state after second == after first.

    This tests whether ``_apply_workspace_edit_to_disk`` is idempotent
    for the ``changes`` wire shape.  Because the applier re-reads the file
    for each call, a second apply of the *same* range edit operates on
    already-mutated bytes — the property surfaces real divergence.

    Currently marked xfail (B4-BUG-01): zero-width insertions violate
    idempotence.  See module docstring for details.
    """
    sl, sc, el, ec, new_text = data.draw(_edit_st(file_content))

    with tempfile.TemporaryDirectory() as tmp_dir:
        src = Path(tmp_dir) / "src.py"
        src.write_text(file_content, encoding="utf-8")

        workspace_edit: dict = {
            "changes": {
                src.as_uri(): [
                    {
                        "range": {
                            "start": {"line": sl, "character": sc},
                            "end": {"line": el, "character": ec},
                        },
                        "newText": new_text,
                    }
                ]
            }
        }

        # First apply: mutates the file.
        _apply_workspace_edit_to_disk(workspace_edit)
        after_first = src.read_bytes()

        # Second apply: operates on the already-mutated file.
        _apply_workspace_edit_to_disk(workspace_edit)
        after_second = src.read_bytes()

    assert after_first == after_second, (
        f"Idempotence violated.\n"
        f"  Pre  = {file_content!r}\n"
        f"  Edit = range({sl},{sc})..({el},{ec}) -> {new_text!r}\n"
        f"  After1 = {after_first!r}\n"
        f"  After2 = {after_second!r}"
    )
