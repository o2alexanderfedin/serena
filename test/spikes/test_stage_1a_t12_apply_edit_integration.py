"""T12 — applyEdit capture register integration check via rust-analyzer.

Drives an executeCommand call that does NOT trigger applyEdit
(rust-analyzer/analyzerStatus is read-only) and asserts the drained
list is empty. The capture path itself is unit-tested in T2/T8;
this confirms the wiring survives a real LSP session.

If rust-analyzer/analyzerStatus is unsupported on the local RA build
(LSP -32601 per S4/S5 findings), the test asserts the failure surfaces
as a SolidLSPException with code -32601 — i.e., the wiring still works,
just the command isn't available.
"""

from __future__ import annotations

import pytest

from solidlsp.ls import SolidLanguageServer
from solidlsp.ls_exceptions import SolidLSPException


def test_execute_command_against_rust_analyzer_no_apply_edits(
    rust_lsp: SolidLanguageServer,
) -> None:
    """analyzerStatus is read-only; should not fire applyEdit reverse-requests."""
    try:
        response, drained = rust_lsp.execute_command("rust-analyzer/analyzerStatus", [])
    except SolidLSPException as exc:
        # If RA build doesn't support analyzerStatus (LSP -32601), the
        # facade still ran — just the command was rejected. The wiring
        # contract (capture+drain) is unaffected. Confirm the buffer is
        # still empty after the failed call.
        assert "-32601" in str(exc) or "MethodNotFound" in str(exc) or "method not found" in str(exc).lower()
        assert rust_lsp.pop_pending_apply_edits() == []
        return
    # analyzerStatus returns either a string (status text) or None/dict
    # depending on RA build; the contract is type-flexible.
    assert response is None or isinstance(response, (str, dict, list))
    assert drained == []  # read-only command must not fire applyEdit
