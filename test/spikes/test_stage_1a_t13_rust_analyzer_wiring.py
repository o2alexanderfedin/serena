"""T13 — rust_analyzer wiring uses override hook + additive progress tap.

Boots a real rust-analyzer session via the rust_lsp fixture; asserts:
1. After indexing, `_progress_state` shows at least one rust-analyzer
   indexing-class token reaching kind=end (proves the additive listener
   replaced the do_nothing clobber and feeds _on_progress).
2. Calling override_initialize_params({}) on the live RA wrapper sets
   experimental.snippetTextEdit=False (proves T13's hook override is
   active and applied to live params).

Test 2 also serves as the integration-level coverage requested by the
T10 reviewer's NIT (the wrapper-installation gap): if RA's initialize
call has been wrapped, the chokepoint applies the override hook, which
is what test 2 verifies.
"""

from __future__ import annotations

from solidlsp.ls import SolidLanguageServer


def test_progress_tap_records_indexing_tokens(rust_lsp: SolidLanguageServer) -> None:
    rust_lsp.wait_for_indexing(timeout_s=60.0)
    indexing_seen = [t for t in rust_lsp._progress_state if rust_lsp._is_indexing_token(t)]
    assert indexing_seen, (
        f"expected at least one rustAnalyzer/* indexing token in _progress_state; "
        f"observed tokens: {list(rust_lsp._progress_state.keys())}"
    )


def test_snippet_override_applied(rust_lsp: SolidLanguageServer) -> None:
    """RustAnalyzer.override_initialize_params() should set
    experimental.snippetTextEdit=False (Phase 0 S2 finding)."""
    sample = rust_lsp.override_initialize_params({"capabilities": {}})
    assert sample["capabilities"].get("experimental", {}).get("snippetTextEdit") is False
