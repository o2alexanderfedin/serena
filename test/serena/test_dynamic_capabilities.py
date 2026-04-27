from __future__ import annotations

from solidlsp.dynamic_capabilities import DynamicCapabilityRegistry


def test_registry_starts_empty() -> None:
    reg = DynamicCapabilityRegistry()
    assert reg.list_for("basedpyright") == []


def test_register_appends_unique_methods() -> None:
    reg = DynamicCapabilityRegistry()
    reg.register("basedpyright", "textDocument/publishDiagnostics")
    reg.register("basedpyright", "textDocument/publishDiagnostics")
    reg.register("basedpyright", "textDocument/codeAction")
    assert reg.list_for("basedpyright") == [
        "textDocument/publishDiagnostics",
        "textDocument/codeAction",
    ]


def test_register_isolates_per_server() -> None:
    reg = DynamicCapabilityRegistry()
    reg.register("basedpyright", "textDocument/publishDiagnostics")
    reg.register("ruff", "workspace/executeCommand")
    assert reg.list_for("basedpyright") == ["textDocument/publishDiagnostics"]
    assert reg.list_for("ruff") == ["workspace/executeCommand"]
    assert reg.list_for("absent") == []
