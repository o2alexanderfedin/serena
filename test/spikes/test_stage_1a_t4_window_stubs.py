"""T4 — window stubs.

Auto-accept the first offered action on showMessageRequest (RA "Reload
workspace?" prompts) and ACK workDoneProgress/create. §4.1 MVP scope.
"""

from __future__ import annotations

from solidlsp.ls import SolidLanguageServer


def test_show_message_request_returns_first_action(slim_sls: SolidLanguageServer) -> None:
    out = slim_sls._handle_show_message_request(
        {"type": 3, "message": "Reload?", "actions": [{"title": "Yes"}, {"title": "No"}]}
    )
    assert out == {"title": "Yes"}


def test_show_message_request_no_actions_returns_null(slim_sls: SolidLanguageServer) -> None:
    assert slim_sls._handle_show_message_request({"type": 3, "message": "fyi"}) is None


def test_show_message_request_empty_actions_returns_null(slim_sls: SolidLanguageServer) -> None:
    """Defensive: explicit empty `actions` list should also return None, not raise."""
    assert slim_sls._handle_show_message_request({"type": 3, "message": "fyi", "actions": []}) is None


def test_work_done_progress_create_returns_null(slim_sls: SolidLanguageServer) -> None:
    assert slim_sls._handle_work_done_progress_create({"token": "indexing-1"}) is None
