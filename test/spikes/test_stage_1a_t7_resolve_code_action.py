"""T7 — resolve_code_action facade.

Echo-style unit tests with a fake server (no LSP boot needed):
- Standard case: server returns a resolved action; facade returns it.
- Defensive: server returns None (unsupported); facade returns the input
  action unchanged so callers can use the response uniformly.
- Wire shape: facade emits codeAction/resolve with the unresolved action
  as the params payload.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from solidlsp.ls import SolidLanguageServer


def test_resolve_returns_server_response(slim_sls: SolidLanguageServer) -> None:
    fake_server = MagicMock()
    fake_server.send_request.return_value = {"title": "x", "edit": {"changes": {}}}
    slim_sls.server = fake_server
    out = slim_sls.resolve_code_action({"title": "x", "data": {"id": 1}})
    fake_server.send_request.assert_called_once()
    args, _kwargs = fake_server.send_request.call_args
    assert args[0] == "codeAction/resolve"
    assert args[1] == {"title": "x", "data": {"id": 1}}
    assert out == {"title": "x", "edit": {"changes": {}}}


def test_resolve_returns_action_unchanged_when_server_returns_none(slim_sls: SolidLanguageServer) -> None:
    fake_server = MagicMock()
    fake_server.send_request.return_value = None
    slim_sls.server = fake_server
    action = {"title": "y", "edit": {"changes": {}}}
    assert slim_sls.resolve_code_action(action) == action


def test_resolve_returns_action_unchanged_when_server_returns_non_dict(slim_sls: SolidLanguageServer) -> None:
    """Defensive: malformed server returning a list/string/etc must not break callers."""
    fake_server = MagicMock()
    fake_server.send_request.return_value = ["not", "a", "dict"]
    slim_sls.server = fake_server
    action = {"title": "z", "edit": {"changes": {}}}
    assert slim_sls.resolve_code_action(action) == action
