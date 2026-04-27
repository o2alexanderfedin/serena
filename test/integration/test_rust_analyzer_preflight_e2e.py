"""End-to-end (booted-LSP) preflight test for the Leaf-02 RustAnalyzer override.

The 3 unit tests in
``test/solidlsp/rust/test_rust_analyzer_detection.py:575-654`` cover the
``RustAnalyzer.request_code_actions`` preflight by stubbing out
``__init__`` and patching the parent-class method. That gives fast, free
coverage of the override's logic — but it does NOT prove the override
actually fires when a real rust-analyzer process is on the other end of
the wire.

This module closes that gap. It boots a real rust-analyzer against the
``calcrs`` fixture (via the session-scoped ``ra_lsp`` fixture from
``test/integration/conftest.py``), then probes ``request_code_actions``
with an end position past EOF and asserts:

  1. ``ValueError`` is raised before any LSP request leaves the harness.
  2. The parent ``SolidLanguageServer.request_code_actions`` is never
     called (no wire round-trip), proven by patching the parent method
     with a recording mock for the duration of the test.

The test skips cleanly on hosts without ``rust-analyzer`` on PATH
(matching the existing ``ra_lsp`` fixture's contract via
``_require_binary``).

Author: AI Hive(R).
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from solidlsp.ls import SolidLanguageServer


@pytest.mark.rust
@pytest.mark.skipif(
    shutil.which("rust-analyzer") is None,
    reason="rust-analyzer binary required on PATH for booted-LSP preflight test",
)
def test_preflight_raises_before_lsp_traffic_on_real_rust_analyzer(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    """End-to-end proof: preflight fires before any LSP wire traffic.

    Boots rust-analyzer via the session-scoped ``ra_lsp`` fixture, then
    calls ``request_code_actions`` with ``end`` deliberately past EOF.
    Two guarantees verified:

      * ``ValueError`` is raised (preflight contract).
      * The parent class's ``request_code_actions`` is never invoked
        (no wire round-trip — the override stops the request locally).
    """
    from solidlsp.language_servers.rust_analyzer import RustAnalyzer

    lib_path = str(calcrs_workspace / "calcrs" / "src" / "lib.rs")
    assert Path(lib_path).is_file(), f"fixture file missing: {lib_path}"

    # The booted ``ra_lsp`` instance is the RustAnalyzer adapter; its MRO
    # parent is ``SolidLanguageServer``. Patch the parent method on the
    # MRO directly so we observe whether the override delegated upward.
    parent_cls = RustAnalyzer.__mro__[1]
    with patch.object(parent_cls, "request_code_actions") as parent_call:
        with pytest.raises(ValueError, match="out of range"):
            ra_lsp.request_code_actions(
                file=lib_path,
                start={"line": 0, "character": 0},
                end={"line": 9_999_999, "character": 0},
                diagnostics=[],
            )

    # Critical: the override must short-circuit before any wire traffic.
    # If the parent was called the LSP request would have left the
    # harness — defeating the whole point of the local preflight.
    parent_call.assert_not_called()
