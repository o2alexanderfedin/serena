"""DLp5 — unit tests for ``MultiServerCoordinator.execute_command_allowlist``.

Spec reference: dynamic LSP capability spec § 4.6 / Phase 5.

Tests cover:
- Live commands from ``executeCommandProvider.commands`` in ServerCapabilities.
- Fallback when ServerCapabilities has no ``executeCommandProvider``.
- Fallback when ``executeCommandProvider`` is present but ``commands`` is absent.
- Dynamic registration for ``workspace/executeCommand`` appends commands.
- Union across multiple servers in the pool.
- ``executeCommandProvider: true`` (no commands list) → fallback.
- Empty ``commands`` list → fallback.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from serena.refactoring._async_check import AWAITED_SERVER_METHODS
from serena.refactoring.multi_server import MultiServerCoordinator
from solidlsp.dynamic_capabilities import DynamicCapabilityRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_server(server_id: str, caps: dict[str, Any]) -> Any:
    """Create a fake async-compatible server with the given ServerCapabilities."""
    server = MagicMock()
    for method_name in AWAITED_SERVER_METHODS:
        getattr(server, method_name)._o2_async_callable = True
    server.server_id = server_id
    server.server_capabilities = MagicMock(return_value=caps)
    return server


def _empty_registry() -> DynamicCapabilityRegistry:
    return DynamicCapabilityRegistry()


_FALLBACK_PYTHON: frozenset[str] = frozenset({
    "pylsp.executeCommand",
    "ruff.applyAutofix",
    "basedpyright.addImport",
})

_FALLBACK_RUST: frozenset[str] = frozenset({
    "rust-analyzer.runFlycheck",
    "rust-analyzer.expandMacro",
})


# ---------------------------------------------------------------------------
# Source 1: executeCommandProvider.commands from ServerCapabilities
# ---------------------------------------------------------------------------


class TestExecuteCommandAllowlistFromServerCapabilities:
    def test_commands_from_caps_returned(self) -> None:
        """Live commands from executeCommandProvider.commands are used."""
        caps = {
            "executeCommandProvider": {
                "commands": ["custom.myCommand", "custom.otherCommand"],
            },
        }
        server = _make_server("basedpyright", caps)
        coord = MultiServerCoordinator(
            servers={"basedpyright": server},
            dynamic_registry=_empty_registry(),
            catalog=None,
        )
        result = coord.execute_command_allowlist("basedpyright", _FALLBACK_PYTHON)
        assert "custom.myCommand" in result
        assert "custom.otherCommand" in result

    def test_fallback_not_included_when_live_data_present(self) -> None:
        """Fallback commands NOT merged when live data is available."""
        caps = {
            "executeCommandProvider": {
                "commands": ["custom.myCommand"],
            },
        }
        server = _make_server("basedpyright", caps)
        coord = MultiServerCoordinator(
            servers={"basedpyright": server},
            dynamic_registry=_empty_registry(),
            catalog=None,
        )
        result = coord.execute_command_allowlist("basedpyright", _FALLBACK_PYTHON)
        # Fallback commands should NOT be in result when live data is present.
        assert "pylsp.executeCommand" not in result
        assert "ruff.applyAutofix" not in result

    def test_execute_command_provider_boolean_true_uses_fallback(self) -> None:
        """executeCommandProvider: true (no commands list) → fallback."""
        caps = {"executeCommandProvider": True}
        server = _make_server("basedpyright", caps)
        coord = MultiServerCoordinator(
            servers={"basedpyright": server},
            dynamic_registry=_empty_registry(),
            catalog=None,
        )
        result = coord.execute_command_allowlist("basedpyright", _FALLBACK_PYTHON)
        assert result == _FALLBACK_PYTHON

    def test_empty_commands_list_uses_fallback(self) -> None:
        """executeCommandProvider.commands = [] → fallback."""
        caps = {"executeCommandProvider": {"commands": []}}
        server = _make_server("basedpyright", caps)
        coord = MultiServerCoordinator(
            servers={"basedpyright": server},
            dynamic_registry=_empty_registry(),
            catalog=None,
        )
        result = coord.execute_command_allowlist("basedpyright", _FALLBACK_PYTHON)
        assert result == _FALLBACK_PYTHON

    def test_no_execute_command_provider_uses_fallback(self) -> None:
        """No executeCommandProvider field → fallback."""
        caps = {"definitionProvider": True}
        server = _make_server("basedpyright", caps)
        coord = MultiServerCoordinator(
            servers={"basedpyright": server},
            dynamic_registry=_empty_registry(),
            catalog=None,
        )
        result = coord.execute_command_allowlist("basedpyright", _FALLBACK_PYTHON)
        assert result == _FALLBACK_PYTHON

    def test_server_not_in_pool_uses_fallback(self) -> None:
        """Unknown server_id → fallback returned."""
        coord = MultiServerCoordinator(
            servers={},
            dynamic_registry=_empty_registry(),
            catalog=None,
        )
        result = coord.execute_command_allowlist("nonexistent", _FALLBACK_PYTHON)
        assert result == _FALLBACK_PYTHON


# ---------------------------------------------------------------------------
# Source 2: dynamic registration appends commands
# ---------------------------------------------------------------------------


class TestExecuteCommandAllowlistDynamicRegistration:
    def test_dynamic_registration_commands_appended(self) -> None:
        """workspace/executeCommand dynamic registration adds commands to live set."""
        caps = {
            "executeCommandProvider": {
                "commands": ["static.command"],
            },
        }
        server = _make_server("ruff", caps)
        registry = DynamicCapabilityRegistry()
        registry.register(
            "ruff",
            "reg-exec-001",
            "workspace/executeCommand",
            register_options={"commands": ["dynamic.newCommand"]},
        )
        coord = MultiServerCoordinator(
            servers={"ruff": server},
            dynamic_registry=registry,
            catalog=None,
        )
        result = coord.execute_command_allowlist("ruff", _FALLBACK_PYTHON)
        assert "static.command" in result
        assert "dynamic.newCommand" in result

    def test_dynamic_registration_without_caps_replaces_fallback(self) -> None:
        """Dynamic registration alone (no static caps) provides live commands."""
        # No executeCommandProvider in caps.
        caps: dict[str, Any] = {}
        server = _make_server("ruff", caps)
        registry = DynamicCapabilityRegistry()
        registry.register(
            "ruff",
            "reg-exec-002",
            "workspace/executeCommand",
            register_options={"commands": ["dynamic.onlyCommand"]},
        )
        coord = MultiServerCoordinator(
            servers={"ruff": server},
            dynamic_registry=registry,
            catalog=None,
        )
        result = coord.execute_command_allowlist("ruff", _FALLBACK_PYTHON)
        assert "dynamic.onlyCommand" in result
        # Fallback NOT included since live data is present.
        assert "pylsp.executeCommand" not in result

    def test_dynamic_registration_wrong_server_not_included(self) -> None:
        """Dynamic registration for a different server does not contaminate result."""
        caps: dict[str, Any] = {}
        server = _make_server("ruff", caps)
        registry = DynamicCapabilityRegistry()
        registry.register(
            "basedpyright",  # different server
            "reg-exec-003",
            "workspace/executeCommand",
            register_options={"commands": ["basedpyright.specialCommand"]},
        )
        coord = MultiServerCoordinator(
            servers={"ruff": server},
            dynamic_registry=registry,
            catalog=None,
        )
        result = coord.execute_command_allowlist("ruff", _FALLBACK_PYTHON)
        # basedpyright's command must NOT appear for ruff.
        assert "basedpyright.specialCommand" not in result
        # No live data for ruff → fallback.
        assert result == _FALLBACK_PYTHON

    def test_dynamic_registration_unregistered_reverts_to_fallback(self) -> None:
        """After unregistering, live data is empty → fallback used."""
        caps: dict[str, Any] = {}
        server = _make_server("ruff", caps)
        registry = DynamicCapabilityRegistry()
        registry.register(
            "ruff",
            "reg-exec-004",
            "workspace/executeCommand",
            register_options={"commands": ["dynamic.cmd"]},
        )
        registry.unregister("ruff", "reg-exec-004")  # remove it
        coord = MultiServerCoordinator(
            servers={"ruff": server},
            dynamic_registry=registry,
            catalog=None,
        )
        result = coord.execute_command_allowlist("ruff", _FALLBACK_PYTHON)
        assert "dynamic.cmd" not in result
        assert result == _FALLBACK_PYTHON


# ---------------------------------------------------------------------------
# Multi-server union (pool use case)
# ---------------------------------------------------------------------------


class TestExecuteCommandAllowlistMultiServerUnion:
    def test_union_across_multiple_servers(self) -> None:
        """Commands from different servers in the pool are united by the caller."""
        pylsp_caps = {
            "executeCommandProvider": {"commands": ["pylsp.someCommand"]},
        }
        ruff_caps = {
            "executeCommandProvider": {"commands": ["ruff.applyAutofix"]},
        }
        pylsp_server = _make_server("pylsp-rope", pylsp_caps)
        ruff_server = _make_server("ruff", ruff_caps)
        registry = _empty_registry()
        coord = MultiServerCoordinator(
            servers={"pylsp-rope": pylsp_server, "ruff": ruff_server},
            dynamic_registry=registry,
            catalog=None,
        )
        # Union manually (mirrors what the tool does).
        allowlist: frozenset[str] = frozenset()
        for sid in coord.servers:
            allowlist = allowlist | coord.execute_command_allowlist(sid, _FALLBACK_PYTHON)
        assert "pylsp.someCommand" in allowlist
        assert "ruff.applyAutofix" in allowlist

    def test_one_server_has_caps_other_uses_fallback_union(self) -> None:
        """When one server has caps and another doesn't, union includes both."""
        pylsp_caps = {
            "executeCommandProvider": {"commands": ["pylsp.someCommand"]},
        }
        basedpyright_caps: dict[str, Any] = {}  # no executeCommandProvider

        pylsp_server = _make_server("pylsp-rope", pylsp_caps)
        bp_server = _make_server("basedpyright", basedpyright_caps)
        registry = _empty_registry()
        coord = MultiServerCoordinator(
            servers={"pylsp-rope": pylsp_server, "basedpyright": bp_server},
            dynamic_registry=registry,
            catalog=None,
        )
        pylsp_allowlist = coord.execute_command_allowlist("pylsp-rope", _FALLBACK_PYTHON)
        bp_allowlist = coord.execute_command_allowlist("basedpyright", _FALLBACK_PYTHON)
        # pylsp-rope has live data → no fallback.
        assert "pylsp.someCommand" in pylsp_allowlist
        assert "ruff.applyAutofix" not in pylsp_allowlist
        # basedpyright has no caps → fallback.
        assert bp_allowlist == _FALLBACK_PYTHON
