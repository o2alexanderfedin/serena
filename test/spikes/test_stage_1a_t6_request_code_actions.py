"""T6 — request_code_actions facade.

Two tests:
- Unit test using a fake server (no LSP boot needed): pins the wire shape
  the facade emits and the contract that the response is returned as-is.
- Integration test against the seed-Rust rust-analyzer: confirms the call
  succeeds and yields a list (possibly empty per range).

Phase 0 S6: rust-analyzer is deferred-resolution; top-level response is
metadata only. T7 introduces resolve_code_action() for the second phase.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from solidlsp.ls import SolidLanguageServer


def test_request_code_actions_emits_correct_wire_shape(slim_sls: SolidLanguageServer) -> None:
    fake_server = MagicMock()
    fake_server.send_request.return_value = []
    slim_sls.server = fake_server
    actions = slim_sls.request_code_actions(
        file="/tmp/foo.rs",
        start={"line": 5, "character": 0},
        end={"line": 5, "character": 10},
        only=["refactor.extract"],
        trigger_kind=1,
        diagnostics=[{"range": {}, "message": "x"}],
    )
    assert actions == []
    args, _kwargs = fake_server.send_request.call_args
    assert args[0] == "textDocument/codeAction"
    params = args[1]
    assert params["textDocument"]["uri"].startswith("file:///")
    assert params["range"] == {"start": {"line": 5, "character": 0}, "end": {"line": 5, "character": 10}}
    assert params["context"]["only"] == ["refactor.extract"]
    assert params["context"]["triggerKind"] == 1
    assert params["context"]["diagnostics"] == [{"range": {}, "message": "x"}]


def test_request_code_actions_omits_only_when_none(slim_sls: SolidLanguageServer) -> None:
    fake_server = MagicMock()
    fake_server.send_request.return_value = None
    slim_sls.server = fake_server
    actions = slim_sls.request_code_actions(
        file="/tmp/foo.rs",
        start={"line": 0, "character": 0},
        end={"line": 0, "character": 1},
    )
    args, _kwargs = fake_server.send_request.call_args
    assert "only" not in args[1]["context"]
    # Defensive: server returning None must not break callers; facade returns [].
    assert actions == []


def test_request_code_actions_returns_list_against_rust_analyzer(rust_lsp: SolidLanguageServer, seed_rust_root: Path) -> None:
    """Integration: hits a real rust-analyzer. Asserts the call SUCCEEDS and
    returns a list — not that any action surfaces (RA may legitimately
    return [] for the chosen range)."""
    lib_rs = seed_rust_root / "src" / "lib.rs"
    text = lib_rs.read_text(encoding="utf-8")
    line0 = next((i for i, ln in enumerate(text.splitlines()) if ln.strip().startswith("pub fn ")), 0)
    actions = rust_lsp.request_code_actions(
        file=str(lib_rs),
        start={"line": line0, "character": 0},
        end={"line": line0, "character": 10},
        only=None,
        trigger_kind=2,
        diagnostics=[],
    )
    assert isinstance(actions, list)
