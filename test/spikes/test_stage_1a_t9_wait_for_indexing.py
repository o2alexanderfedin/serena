"""T9 — wait_for_indexing aggregates $/progress end events.

Pure unit test: simulates a tap-fed sequence of $/progress events and
verifies wait_for_indexing returns once all indexing-class tokens have
reached kind=end. The actual rust_analyzer.py listener subscription is
T13's job.

Token classification verified against Phase 0 S1's captured token set
(rustAnalyzer/{Fetching, Building CrateGraph, Building compile-time-deps,
Loading proc-macros, Roots Scanned, cachePriming}, plus
rust-analyzer/flycheck/N).
"""

from __future__ import annotations

import threading

import pytest

from solidlsp.ls import SolidLanguageServer


@pytest.fixture
def progress_sls(slim_sls: SolidLanguageServer) -> SolidLanguageServer:
    """slim_sls + the T9 progress-state attributes."""
    slim_sls._progress_state = {}
    slim_sls._progress_lock = threading.Lock()
    slim_sls._progress_event = threading.Event()
    return slim_sls


def test_indexing_token_classification_recognized(progress_sls: SolidLanguageServer) -> None:
    """All seven Phase 0 S1 token classes must classify as indexing."""
    assert progress_sls._is_indexing_token("rustAnalyzer/Fetching") is True
    assert progress_sls._is_indexing_token("rustAnalyzer/Building CrateGraph") is True
    assert progress_sls._is_indexing_token("rustAnalyzer/Building compile-time-deps") is True
    assert progress_sls._is_indexing_token("rustAnalyzer/Loading proc-macros") is True
    assert progress_sls._is_indexing_token("rustAnalyzer/Roots Scanned") is True
    assert progress_sls._is_indexing_token("rustAnalyzer/cachePriming") is True
    assert progress_sls._is_indexing_token("rust-analyzer/flycheck/0") is True
    assert progress_sls._is_indexing_token("rust-analyzer/flycheck/3") is True


def test_non_indexing_tokens_classified_false(progress_sls: SolidLanguageServer) -> None:
    """Anything not in the indexing-class prefix list must classify as non-indexing."""
    assert progress_sls._is_indexing_token("pylsp:document_processing") is False
    assert progress_sls._is_indexing_token("ruff:lint") is False
    assert progress_sls._is_indexing_token("basedpyright:checking") is False
    assert progress_sls._is_indexing_token("") is False


def test_on_progress_records_kind_state(progress_sls: SolidLanguageServer) -> None:
    progress_sls._on_progress({"token": "rustAnalyzer/Fetching", "value": {"kind": "begin"}})
    assert progress_sls._progress_state["rustAnalyzer/Fetching"] == "begin"
    progress_sls._on_progress({"token": "rustAnalyzer/Fetching", "value": {"kind": "end"}})
    assert progress_sls._progress_state["rustAnalyzer/Fetching"] == "end"


def test_on_progress_ignores_malformed_payload(progress_sls: SolidLanguageServer) -> None:
    """Defensive: payloads without token/value/kind must not crash, must not record state."""
    progress_sls._on_progress({})  # no token
    progress_sls._on_progress({"token": 123, "value": {"kind": "begin"}})  # non-string token
    progress_sls._on_progress({"token": "x", "value": {}})  # no kind
    progress_sls._on_progress({"token": "x", "value": {"kind": "weird"}})  # unknown kind
    assert progress_sls._progress_state == {}


def test_wait_for_indexing_returns_when_all_indexing_tokens_end(progress_sls: SolidLanguageServer) -> None:
    progress_sls._on_progress({"token": "rustAnalyzer/Fetching", "value": {"kind": "begin"}})
    progress_sls._on_progress({"token": "rustAnalyzer/cachePriming", "value": {"kind": "begin"}})

    def finish() -> None:
        progress_sls._on_progress({"token": "rustAnalyzer/Fetching", "value": {"kind": "end"}})
        progress_sls._on_progress({"token": "rustAnalyzer/cachePriming", "value": {"kind": "end"}})

    t = threading.Timer(0.05, finish)
    t.start()
    try:
        assert progress_sls.wait_for_indexing(timeout_s=2.0) is True
    finally:
        t.cancel()


def test_wait_for_indexing_times_out_when_no_progress_seen(progress_sls: SolidLanguageServer) -> None:
    progress_sls._on_progress({"token": "rustAnalyzer/Fetching", "value": {"kind": "begin"}})
    assert progress_sls.wait_for_indexing(timeout_s=0.1) is False


def test_wait_for_indexing_returns_immediately_when_already_complete(progress_sls: SolidLanguageServer) -> None:
    """If indexing already finished before wait_for_indexing is called, return True without blocking."""
    progress_sls._on_progress({"token": "rustAnalyzer/Fetching", "value": {"kind": "begin"}})
    progress_sls._on_progress({"token": "rustAnalyzer/Fetching", "value": {"kind": "end"}})
    assert progress_sls.wait_for_indexing(timeout_s=2.0) is True


def test_wait_for_indexing_resets_event_for_next_call(progress_sls: SolidLanguageServer) -> None:
    """After a successful wait, a subsequent wait waits for a NEW indexing cycle."""
    progress_sls._on_progress({"token": "rustAnalyzer/Fetching", "value": {"kind": "begin"}})
    progress_sls._on_progress({"token": "rustAnalyzer/Fetching", "value": {"kind": "end"}})
    assert progress_sls.wait_for_indexing(timeout_s=2.0) is True
    # Event was cleared. New cycle:
    progress_sls._on_progress({"token": "rustAnalyzer/cachePriming", "value": {"kind": "begin"}})
    assert progress_sls.wait_for_indexing(timeout_s=0.1) is False  # still active
