"""T3 — workspace/configuration + client/registerCapability auto-responders.

Phase 0 P4 finding: basedpyright BLOCKS on these requests if unanswered.
Default-safe responses: empty config object per requested item, null for
register/unregister. rust-analyzer mid-session queries also flow through
this path.

Pure unit test: bypasses __init__ via __new__-on-concrete-subclass since
SolidLanguageServer.ABC requires _start_server. Mirrors the T2 pattern.
"""

from __future__ import annotations

from solidlsp.ls import SolidLanguageServer


def test_configuration_returns_one_empty_per_item(slim_sls: SolidLanguageServer) -> None:
    out = slim_sls._handle_workspace_configuration({"items": [{"section": "rust-analyzer"}, {"section": "x.y"}]})
    assert out == [{}, {}]


def test_configuration_handles_empty_items(slim_sls: SolidLanguageServer) -> None:
    assert slim_sls._handle_workspace_configuration({"items": []}) == []


def test_configuration_handles_missing_items_key(slim_sls: SolidLanguageServer) -> None:
    """Defensive: malformed payload without 'items' should return empty list, not raise."""
    assert slim_sls._handle_workspace_configuration({}) == []


def test_register_capability_returns_null(slim_sls: SolidLanguageServer) -> None:
    out = slim_sls._handle_register_capability({"registrations": [{"id": "x", "method": "workspace/didChangeWatchedFiles"}]})
    assert out is None


def test_unregister_capability_returns_null(slim_sls: SolidLanguageServer) -> None:
    assert slim_sls._handle_unregister_capability({"unregisterations": [{"id": "x", "method": "x"}]}) is None
