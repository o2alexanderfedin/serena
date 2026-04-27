"""Stage v0.2.0-followup-01c — base ``_handle_register_capability``
records dynamic LSP method registrations into the runtime registry."""
from __future__ import annotations

from typing import Any

from serena.tools.scalpel_runtime import ScalpelRuntime
from solidlsp.language_servers.basedpyright_server import BasedpyrightServer
from solidlsp.language_servers.pylsp_server import PylspServer


def _invoke_handler(server_cls: type, params: dict[str, Any]) -> None:
    """Bypass heavy LSP init and directly invoke the handler."""
    instance = object.__new__(server_cls)
    # The handler reads ``type(self).server_id`` and the runtime singleton —
    # neither requires the heavy SolidLanguageServer init to be present.
    instance._handle_register_capability(params)


def test_basedpyright_handler_records_into_runtime_registry() -> None:
    ScalpelRuntime.reset_for_testing()
    try:
        params = {
            "registrations": [
                {"id": "diag-1", "method": "textDocument/publishDiagnostics"},
                {"id": "ca-1", "method": "textDocument/codeAction"},
                {"id": "ca-1-dup", "method": "textDocument/codeAction"},
            ]
        }
        _invoke_handler(BasedpyrightServer, params)

        registry = ScalpelRuntime.instance().dynamic_capability_registry()
        assert registry.list_for("basedpyright") == [
            "textDocument/publishDiagnostics",
            "textDocument/codeAction",
        ]
        assert registry.list_for("pylsp-base") == []
    finally:
        ScalpelRuntime.reset_for_testing()


def test_pylsp_handler_records_under_pylsp_base() -> None:
    ScalpelRuntime.reset_for_testing()
    try:
        params = {
            "registrations": [
                {"id": "watch-1", "method": "workspace/didChangeWatchedFiles"},
            ]
        }
        _invoke_handler(PylspServer, params)

        registry = ScalpelRuntime.instance().dynamic_capability_registry()
        assert registry.list_for("pylsp-base") == [
            "workspace/didChangeWatchedFiles",
        ]
    finally:
        ScalpelRuntime.reset_for_testing()


def test_handler_ignores_malformed_params() -> None:
    """No ``registrations`` key, non-dict entries, missing/non-string method —
    handler must not raise."""
    ScalpelRuntime.reset_for_testing()
    try:
        for params in (
            {},
            {"registrations": []},
            {"registrations": [{"id": "x"}]},  # no method
            {"registrations": [{"method": 123}]},  # non-string
            {"registrations": ["not-a-dict"]},  # non-dict entry
        ):
            _invoke_handler(BasedpyrightServer, params)

        registry = ScalpelRuntime.instance().dynamic_capability_registry()
        assert registry.list_for("basedpyright") == []
    finally:
        ScalpelRuntime.reset_for_testing()
