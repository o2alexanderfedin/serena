from __future__ import annotations

import pytest

from solidlsp.dynamic_capabilities import DynamicCapabilityRegistry, DynamicRegistration


def test_registry_starts_empty() -> None:
    reg = DynamicCapabilityRegistry()
    assert reg.list_for("basedpyright") == []


def test_register_appends_unique_methods() -> None:
    reg = DynamicCapabilityRegistry()
    reg.register("basedpyright", "reg-1", "textDocument/publishDiagnostics")
    reg.register("basedpyright", "reg-1", "textDocument/publishDiagnostics")  # same id: overwrite
    reg.register("basedpyright", "reg-2", "textDocument/codeAction")
    assert reg.list_for("basedpyright") == [
        "textDocument/publishDiagnostics",
        "textDocument/codeAction",
    ]


def test_register_isolates_per_server() -> None:
    reg = DynamicCapabilityRegistry()
    reg.register("basedpyright", "reg-A", "textDocument/publishDiagnostics")
    reg.register("ruff", "reg-B", "workspace/executeCommand")
    assert reg.list_for("basedpyright") == ["textDocument/publishDiagnostics"]
    assert reg.list_for("ruff") == ["workspace/executeCommand"]
    assert reg.list_for("absent") == []


# ---------------------------------------------------------------------------
# DLp1 — new tests for id, registerOptions, has(), and unregister()
# ---------------------------------------------------------------------------


def test_register_stores_id_and_method() -> None:
    """Registration id must round-trip through the registry."""
    reg = DynamicCapabilityRegistry()
    reg.register("basedpyright", "my-reg-id", "textDocument/codeAction")
    # has() should confirm the method is present
    assert reg.has("basedpyright", "textDocument/codeAction")


def test_register_stores_register_options() -> None:
    """registerOptions must be stored verbatim alongside id and method."""
    opts = {"documentSelector": [{"language": "python"}], "codeActionKinds": ["refactor.extract"]}
    reg = DynamicCapabilityRegistry()
    reg.register("basedpyright", "reg-opt-1", "textDocument/codeAction", opts)
    # Access the internal record to verify storage (white-box: acceptable for unit test).
    with reg._lock:  # noqa: SLF001 — deliberate white-box access in tests
        entry = reg._by_server["basedpyright"]["reg-opt-1"]  # noqa: SLF001
    assert isinstance(entry, DynamicRegistration)
    assert entry.id == "reg-opt-1"
    assert entry.method == "textDocument/codeAction"
    assert entry.register_options == opts


def test_register_options_defaults_to_empty_mapping() -> None:
    """Omitting registerOptions must store an empty mapping, not None."""
    reg = DynamicCapabilityRegistry()
    reg.register("basedpyright", "reg-no-opts", "textDocument/hover")
    with reg._lock:  # noqa: SLF001
        entry = reg._by_server["basedpyright"]["reg-no-opts"]  # noqa: SLF001
    assert entry.register_options == {}


def test_has_returns_true_after_register() -> None:
    reg = DynamicCapabilityRegistry()
    reg.register("basedpyright", "diag-1", "textDocument/publishDiagnostics")
    assert reg.has("basedpyright", "textDocument/publishDiagnostics") is True


def test_has_returns_false_for_never_registered() -> None:
    reg = DynamicCapabilityRegistry()
    assert reg.has("basedpyright", "textDocument/codeAction") is False
    assert reg.has("absent-server", "textDocument/codeAction") is False


def test_has_returns_false_after_unregister() -> None:
    """Unregistering a capability by id must remove it from has() results."""
    reg = DynamicCapabilityRegistry()
    reg.register("basedpyright", "unreg-1", "textDocument/codeAction")
    assert reg.has("basedpyright", "textDocument/codeAction") is True

    reg.unregister("basedpyright", "unreg-1")
    assert reg.has("basedpyright", "textDocument/codeAction") is False


def test_unregister_is_idempotent() -> None:
    """Unregistering a non-existent id must not raise."""
    reg = DynamicCapabilityRegistry()
    reg.unregister("basedpyright", "non-existent-id")  # should not raise


def test_unregister_leaves_other_registrations_intact() -> None:
    """Unregistering one id must not affect other registrations for the same method."""
    reg = DynamicCapabilityRegistry()
    reg.register("basedpyright", "reg-x", "textDocument/codeAction")
    reg.register("basedpyright", "reg-y", "textDocument/codeAction")  # same method, different id
    reg.unregister("basedpyright", "reg-x")
    # method is still covered by reg-y
    assert reg.has("basedpyright", "textDocument/codeAction") is True


def test_unregister_functional_was_not_noop() -> None:
    """Previously _handle_unregister_capability was a no-op; registry.unregister() must
    now actually remove the entry so that has() reflects the live state."""
    reg = DynamicCapabilityRegistry()
    reg.register("ruff", "exec-1", "workspace/executeCommand")
    assert reg.has("ruff", "workspace/executeCommand") is True

    reg.unregister("ruff", "exec-1")
    assert reg.has("ruff", "workspace/executeCommand") is False
    # list_for should also reflect removal
    assert "workspace/executeCommand" not in reg.list_for("ruff")


def test_list_for_deduplicates_methods() -> None:
    """list_for must return unique method names even when multiple ids cover the same method."""
    reg = DynamicCapabilityRegistry()
    reg.register("basedpyright", "dup-1", "textDocument/codeAction")
    reg.register("basedpyright", "dup-2", "textDocument/codeAction")
    methods = reg.list_for("basedpyright")
    assert methods.count("textDocument/codeAction") == 1


@pytest.mark.parametrize("method", [
    "textDocument/publishDiagnostics",
    "textDocument/codeAction",
    "workspace/executeCommand",
])
def test_has_parametrized_across_methods(method: str) -> None:
    reg = DynamicCapabilityRegistry()
    reg.register("test-server", f"reg-{method}", method)
    assert reg.has("test-server", method) is True
    reg.unregister("test-server", f"reg-{method}")
    assert reg.has("test-server", method) is False
