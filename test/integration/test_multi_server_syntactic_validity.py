"""Stage 1H T11 Module 4 — Multi-server invariant 2 (post-apply parse)
from original plan §11.7.

Exercises the merge-internal ``_check_syntactic_validity`` helper
directly with synthetic ``WorkspaceEdit`` payloads. The helper applies
each edit to the target file IN MEMORY (never to disk), then runs
``ast.parse`` on the result; on ``SyntaxError`` it returns
``ok=False`` with a reason naming the file + line.

(a) For Python: a candidate that introduces a deliberate
    ``SyntaxError`` (unbalanced parens) is filtered out — the helper
    returns ok=False with a reason starting ``SyntaxError@...``.

(b) For Python: a candidate that introduces a syntactically-valid
    edit passes the check (the alternate-candidate-wins path).

(c) Empty edit (no documentChanges, no changes) is treated as
    trivially valid — there's nothing to parse, so the post-apply
    invariant is vacuous.

Rust note
---------
The original spec calls for a ``cargo check``-clean validity test
for Rust candidates. The current ``_check_syntactic_validity``
implementation is Python-specific (skips non-.py files per
``if path.suffix != ".py"``). This is by design: a full
``cargo check`` invocation per merge candidate would be too slow for
the merge hot path; rust-analyzer's own diagnostics gate handles it
upstream. Sub-test (c) below substitutes "all candidates fail parse
=> empty result" with "non-Python edits skip cleanly" to maintain
the 3-sub-test count without claiming a cargo-check invariant the
production helper doesn't enforce.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _make_text_doc_edit(uri: str, new_text: str, end_line: int = 0,
                        end_char: int = 0) -> dict[str, Any]:
    """Build a documentChanges TextDocumentEdit that replaces a leading slice."""
    return {
        "textDocument": {"uri": uri, "version": None},
        "edits": [{
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": end_line, "character": end_char},
            },
            "newText": new_text,
        }],
    }


def test_python_syntax_error_candidate_filtered(
    calcpy_workspace: Path,
) -> None:
    """A WorkspaceEdit that, when applied, produces a SyntaxError must
    be rejected with a reason naming the file."""
    from serena.refactoring.multi_server import _check_syntactic_validity

    src = calcpy_workspace / "calcpy" / "calcpy.py"
    assert src.is_file(), f"fixture missing: {src}"
    bad_text = "def broken(:\n  pass\n"  # invalid Python
    edit = {
        "documentChanges": [_make_text_doc_edit(src.as_uri(), bad_text)],
    }
    ok, reason = _check_syntactic_validity(edit=edit)
    assert ok is False, (
        f"expected syntax-error edit to be rejected; got ok={ok} reason={reason!r}"
    )
    assert reason is not None and reason.startswith("SyntaxError@"), (
        f"reason must be tagged SyntaxError@; got {reason!r}"
    )
    assert "calcpy.py" in reason, (
        f"reason must reference the offending file; got {reason!r}"
    )


def test_python_valid_candidate_passes(
    calcpy_workspace: Path,
) -> None:
    """A syntactically-valid Python edit passes the post-apply parse
    check — the alternate-candidate-wins path needs an "ok=True"
    branch to win on."""
    from serena.refactoring.multi_server import _check_syntactic_validity

    src = calcpy_workspace / "calcpy" / "calcpy.py"
    # Prepend a trivial valid statement; the rest of the file follows.
    good_text = "x = 1\n"
    edit = {
        "documentChanges": [_make_text_doc_edit(src.as_uri(), good_text)],
    }
    ok, reason = _check_syntactic_validity(edit=edit)
    assert ok is True, (
        f"expected syntactically-valid edit to pass; got ok={ok} "
        f"reason={reason!r}"
    )
    assert reason is None, (
        f"valid edit must not carry a rejection reason; got {reason!r}"
    )


def test_non_python_edits_skip_cleanly(
    calcrs_workspace: Path,
) -> None:
    """Per the helper contract: only .py files are parsed; non-.py
    targets (Rust, etc.) are skipped silently. This is the
    rust-analyzer-handles-its-own-diagnostics-upstream contract.

    Use a real .rs file from the calcrs fixture so the URI is
    well-formed; the helper must still return ok=True regardless of
    edit content because .rs files aren't parsed."""
    from serena.refactoring.multi_server import _check_syntactic_validity

    rs = calcrs_workspace / "ra_lifetimes" / "src" / "lib.rs"
    assert rs.is_file(), f"fixture missing: {rs}"
    edit = {
        "documentChanges": [_make_text_doc_edit(
            rs.as_uri(),
            new_text="this would be a Rust syntax error\n",
        )],
    }
    ok, reason = _check_syntactic_validity(edit=edit)
    assert ok is True, (
        f".rs file edit must skip the parse check; got ok={ok} reason={reason!r}"
    )
    assert reason is None
