"""
B4 — WorkspaceEdit applier idempotence (pure-python disk applier, SQ2 fix).

regression: docs/superpowers/specs/2026-05-03-test-coverage-strategy-design.md §6 Phase B B4
regression: v0.3.0-facade-application-complete (parent 2026-04-26)

Property (scoped to zero-width insertions): applying the same pure-insertion
WorkspaceEdit twice via ``_apply_workspace_edit_to_disk`` produces the same
final disk state as applying it once.

Scope note
----------
Only zero-width insertions (start == end, newText non-empty) are tested here.
Deletions and shrink-replacements are excluded because making them idempotent
would require per-call state (a fingerprint of what the range contained before
the first apply).  Insertions are detectable without state: after the first
apply the inserted text appears verbatim at the insertion offset.

B4-BUG-01 (FIXED — SQ2)
------------------------
The applier was NOT idempotent for zero-width insertions (start == end).
Minimal reproducer (pre-fix)::

    file_content = ''
    edit = range(0,0)..(0,0) -> '0'
    after first apply  -> b'0'
    after second apply -> b'00'   # doubled

Fix applied in ``_splice_text_edit`` (facade_support.py): before splicing,
check if ``source[start_offset:start_offset + len(newText)] == newText`` AND
``end_offset <= start_offset + len(newText)``.  If so the edit was already
applied — return ``source`` unchanged.  The I/O layer was also fixed to use
``newline=""`` so ``\\r`` bytes are not silently coerced to ``\\n`` on re-read.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

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


def _insertion_edit_st(content: str) -> st.SearchStrategy[tuple[int, int, int, int, str]]:
    """Return a strategy for a zero-width insertion TextEdit over ``content``.

    Scope: B4-BUG-01 covers pure insertions (start == end, newText non-empty).
    Deletions and shrink-replacements are excluded because their idempotence
    would require per-call state to detect double-apply (we'd need to remember
    the original range content).  Only insertions produce a detectable
    already-applied fingerprint: the inserted text appears verbatim at the
    insertion offset after first apply.
    """
    lines = content.split("\n") if content else [""]
    last_line = max(0, len(lines) - 1)

    @st.composite
    def _build(draw: st.DrawFn) -> tuple[int, int, int, int, str]:
        sl = draw(st.integers(min_value=0, max_value=last_line))
        max_sc = len(lines[sl]) if sl < len(lines) else 0
        sc = draw(st.integers(min_value=0, max_value=max_sc))
        # Zero-width range: end == start
        el, ec = sl, sc
        # Non-empty newText so the insertion is observable
        new_text = draw(st.text(min_size=1, max_size=40))
        return sl, sc, el, ec, new_text

    return _build()


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------


@given(_file_content_st, st.data())
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_apply_workspace_edit_to_disk_is_idempotent(
    file_content: str,
    data: st.DataObject,
) -> None:
    """Applying the same zero-width insertion WorkspaceEdit twice is a no-op.

    Scope: pure insertions (start == end, newText non-empty).  Deletions and
    shrink-replacements are excluded — making those idempotent would require
    per-call state to remember the original range content.

    B4-BUG-01 fixed (SQ2): ``_splice_text_edit`` now checks whether the
    content at the insertion offset already equals ``newText`` before splicing.
    The I/O layer uses ``newline=""`` so ``\\r`` in newText is not silently
    coerced to ``\\n`` on re-read, which would shift subsequent offsets.
    """
    sl, sc, el, ec, new_text = data.draw(_insertion_edit_st(file_content))

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
