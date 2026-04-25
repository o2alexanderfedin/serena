"""T5 — refresh-request stubs.

Server-side cache-invalidation hints. Spec response is null. Required for
basedpyright pull-mode (P4) and rust-analyzer semantic-tokens refresh.
"""

from __future__ import annotations

from solidlsp.ls import SolidLanguageServer


def test_semantic_tokens_refresh_null(slim_sls: SolidLanguageServer) -> None:
    assert slim_sls._handle_semantic_tokens_refresh(None) is None


def test_semantic_tokens_refresh_with_empty_dict_null(slim_sls: SolidLanguageServer) -> None:
    """LSP spec says params is null for these requests; handler must tolerate {} too."""
    assert slim_sls._handle_semantic_tokens_refresh({}) is None


def test_diagnostic_refresh_null(slim_sls: SolidLanguageServer) -> None:
    assert slim_sls._handle_diagnostic_refresh(None) is None


def test_diagnostic_refresh_with_empty_dict_null(slim_sls: SolidLanguageServer) -> None:
    assert slim_sls._handle_diagnostic_refresh({}) is None
