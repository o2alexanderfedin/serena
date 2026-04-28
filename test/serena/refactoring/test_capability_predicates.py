"""DLp2 — unit tests for ``MultiServerCoordinator.supports_method`` (2-tier)
and ``MultiServerCoordinator.supports_kind`` (3-tier).

Spec reference: dynamic LSP capability spec § 4.4, § 7 / test_capability_predicates.py.

All tests use lightweight fake objects — no real LSP processes started.
The _FakeCapServer doubles are intentionally minimal: only the method
shapes used by the predicates (``server_capabilities()``) and the async
methods required by ``assert_servers_async_callable`` (``request_code_actions``
etc.) are implemented.  All four awaited methods are made async so the
constructor validation gate passes.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from serena.refactoring._async_check import AWAITED_SERVER_METHODS
from serena.refactoring.capabilities import CapabilityCatalog, CapabilityRecord
from serena.refactoring.multi_server import MultiServerCoordinator, ProvenanceLiteral
from solidlsp.capability_keys import (
    CODE_ACTION,
    GO_TO_DEFINITION,
    GO_TO_IMPLEMENTATION,
    GO_TO_REFERENCES,
    HOVER,
    PREPARE_RENAME,
    RENAME,
    _METHOD_TO_PROVIDER_KEY,
)
from solidlsp.dynamic_capabilities import DynamicCapabilityRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_async_server_with_caps(
    server_id: str,
    caps: dict[str, Any],
) -> Any:
    """Create an async-compatible fake server with the given ServerCapabilities.

    All four AWAITED_SERVER_METHODS are async MagicMocks so the coordinator
    construction gate passes.  The ``server_capabilities()`` method returns
    the supplied *caps* dict.
    """
    server = MagicMock()
    for method_name in AWAITED_SERVER_METHODS:
        getattr(server, method_name)._o2_async_callable = True
    server.server_id = server_id

    # Return the given caps dict from server_capabilities().
    server.server_capabilities = MagicMock(return_value=caps)
    return server


def _empty_registry() -> DynamicCapabilityRegistry:
    return DynamicCapabilityRegistry()


def _registry_with(server_id: str, method: str) -> DynamicCapabilityRegistry:
    reg = DynamicCapabilityRegistry()
    reg.register(server_id, f"reg-{method}", method)
    return reg


def _catalog_with(*records: CapabilityRecord) -> CapabilityCatalog:
    return CapabilityCatalog(records=records)


def _make_record(language: str, kind: str, source_server: ProvenanceLiteral) -> CapabilityRecord:
    return CapabilityRecord(
        id=f"{language}.{kind}",
        language=language,
        kind=kind,
        source_server=source_server,
    )


# ---------------------------------------------------------------------------
# supports_method — Tier 1: dynamic registry
# ---------------------------------------------------------------------------


class TestSupportsMethodTier1DynamicRegistry:
    """Tier-1 hits the dynamic registry before consulting ServerCapabilities."""

    def test_dynamic_registry_alone_is_sufficient(self) -> None:
        """If the method is in the registry, supports_method returns True even
        if ServerCapabilities is empty."""
        server = _make_async_server_with_caps("basedpyright", {})
        registry = _registry_with("basedpyright", GO_TO_IMPLEMENTATION)
        coord = MultiServerCoordinator(
            servers={"basedpyright": server},
            dynamic_registry=registry,
            catalog=_catalog_with(),
        )
        assert coord.supports_method("basedpyright", GO_TO_IMPLEMENTATION) is True

    def test_dynamic_registry_wrong_server_does_not_help(self) -> None:
        """Registry entry for 'ruff' does not count for 'basedpyright'."""
        server = _make_async_server_with_caps("basedpyright", {})
        registry = _registry_with("ruff", GO_TO_IMPLEMENTATION)
        coord = MultiServerCoordinator(
            servers={"basedpyright": server},
            dynamic_registry=registry,
            catalog=_catalog_with(),
        )
        assert coord.supports_method("basedpyright", GO_TO_IMPLEMENTATION) is False


# ---------------------------------------------------------------------------
# supports_method — Tier 2: ServerCapabilities
# ---------------------------------------------------------------------------


class TestSupportsMethodTier2ServerCapabilities:
    """Tier-2 reads the ServerCapabilities provider field."""

    def test_definition_provider_true(self) -> None:
        server = _make_async_server_with_caps(
            "basedpyright", {"definitionProvider": True}
        )
        coord = MultiServerCoordinator(
            servers={"basedpyright": server},
            dynamic_registry=_empty_registry(),
            catalog=_catalog_with(),
        )
        assert coord.supports_method("basedpyright", GO_TO_DEFINITION) is True

    def test_definition_provider_options_dict(self) -> None:
        """A non-empty options dict is also truthy — the method is supported."""
        server = _make_async_server_with_caps(
            "basedpyright", {"definitionProvider": {"workDoneProgress": True}}
        )
        coord = MultiServerCoordinator(
            servers={"basedpyright": server},
            dynamic_registry=_empty_registry(),
            catalog=_catalog_with(),
        )
        assert coord.supports_method("basedpyright", GO_TO_DEFINITION) is True

    def test_missing_provider_field(self) -> None:
        """Absent provider field → method not supported."""
        server = _make_async_server_with_caps(
            "basedpyright", {"definitionProvider": True}
        )
        coord = MultiServerCoordinator(
            servers={"basedpyright": server},
            dynamic_registry=_empty_registry(),
            catalog=_catalog_with(),
        )
        assert coord.supports_method("basedpyright", GO_TO_IMPLEMENTATION) is False

    def test_provider_false(self) -> None:
        server = _make_async_server_with_caps(
            "basedpyright", {"implementationProvider": False}
        )
        coord = MultiServerCoordinator(
            servers={"basedpyright": server},
            dynamic_registry=_empty_registry(),
            catalog=_catalog_with(),
        )
        assert coord.supports_method("basedpyright", GO_TO_IMPLEMENTATION) is False


# ---------------------------------------------------------------------------
# supports_method — Pyright implementationProvider regression case
# (spec § 6 P2 exit criterion)
# ---------------------------------------------------------------------------


class TestSupportsMethodPyrightRegressionCase:
    """The motivating bug: Pyright omits implementationProvider entirely.

    A synthetic adapter without implementationProvider in its ServerCapabilities
    and without a dynamic registration must return False for
    textDocument/implementation.  This is the Pyright regression case documented
    in the spec and in reference_lsp_capability_gaps.md.
    """

    def test_pyright_no_implementation_provider(self) -> None:
        """Core regression: no implementationProvider → supports_method False."""
        pyright_caps = {
            "definitionProvider": True,
            "referencesProvider": True,
            "hoverProvider": True,
            "renameProvider": True,
            "codeActionProvider": True,
            # implementationProvider intentionally absent — matches real Pyright
        }
        pyright_server = _make_async_server_with_caps("basedpyright", pyright_caps)
        coord = MultiServerCoordinator(
            servers={"basedpyright": pyright_server},
            dynamic_registry=_empty_registry(),
            catalog=_catalog_with(),
        )
        assert (
            coord.supports_method("basedpyright", GO_TO_IMPLEMENTATION) is False
        ), "Pyright lacks implementationProvider; supports_method must return False"

    def test_pyright_definition_works(self) -> None:
        """Positive case: definitionProvider advertised → supports_method True."""
        pyright_caps = {
            "definitionProvider": True,
            # implementationProvider absent
        }
        pyright_server = _make_async_server_with_caps("basedpyright", pyright_caps)
        coord = MultiServerCoordinator(
            servers={"basedpyright": pyright_server},
            dynamic_registry=_empty_registry(),
            catalog=_catalog_with(),
        )
        assert coord.supports_method("basedpyright", GO_TO_DEFINITION) is True

    def test_dynamic_registration_fills_gap(self) -> None:
        """Dynamic registration for implementationProvider bridges the static gap."""
        pyright_caps = {"definitionProvider": True}
        pyright_server = _make_async_server_with_caps("basedpyright", pyright_caps)
        registry = _registry_with("basedpyright", GO_TO_IMPLEMENTATION)
        coord = MultiServerCoordinator(
            servers={"basedpyright": pyright_server},
            dynamic_registry=registry,
            catalog=_catalog_with(),
        )
        assert coord.supports_method("basedpyright", GO_TO_IMPLEMENTATION) is True


# ---------------------------------------------------------------------------
# supports_method — unknown server + unknown method
# ---------------------------------------------------------------------------


class TestSupportsMethodEdgeCases:
    def test_unknown_server_returns_false(self) -> None:
        coord = MultiServerCoordinator(
            servers={},
            dynamic_registry=_empty_registry(),
            catalog=_catalog_with(),
        )
        assert coord.supports_method("non-existent-server", GO_TO_DEFINITION) is False

    def test_unknown_method_returns_false(self) -> None:
        server = _make_async_server_with_caps("ruff", {"definitionProvider": True})
        coord = MultiServerCoordinator(
            servers={"ruff": server},
            dynamic_registry=_empty_registry(),
            catalog=_catalog_with(),
        )
        # Custom or unknown method not in _METHOD_TO_PROVIDER_KEY.
        assert coord.supports_method("ruff", "rust-analyzer/expandMacro") is False

    def test_no_server_capabilities_attribute(self) -> None:
        """Servers that don't expose server_capabilities() are treated as
        empty caps (graceful degradation for test doubles without the method)."""
        server = MagicMock()
        for method_name in AWAITED_SERVER_METHODS:
            getattr(server, method_name)._o2_async_callable = True
        # Do NOT add server_capabilities() — simulate old test-double.
        server.server_capabilities = None  # not callable
        coord = MultiServerCoordinator(
            servers={"ruff": server},
            dynamic_registry=_empty_registry(),
            catalog=_catalog_with(),
        )
        assert coord.supports_method("ruff", GO_TO_DEFINITION) is False


# ---------------------------------------------------------------------------
# supports_method — prepareRename sub-capability (spec § R5)
# ---------------------------------------------------------------------------


class TestSupportsMethodPrepareRename:
    def test_rename_provider_true_without_options_denies_prepare_rename(self) -> None:
        """renameProvider: true without prepareProvider: true is insufficient
        for textDocument/prepareRename per spec § R5."""
        server = _make_async_server_with_caps("pylsp-rope", {"renameProvider": True})
        coord = MultiServerCoordinator(
            servers={"pylsp-rope": server},
            dynamic_registry=_empty_registry(),
            catalog=_catalog_with(),
        )
        assert coord.supports_method("pylsp-rope", PREPARE_RENAME) is False

    def test_rename_provider_with_prepare_provider_true(self) -> None:
        server = _make_async_server_with_caps(
            "pylsp-rope",
            {"renameProvider": {"prepareProvider": True}},
        )
        coord = MultiServerCoordinator(
            servers={"pylsp-rope": server},
            dynamic_registry=_empty_registry(),
            catalog=_catalog_with(),
        )
        assert coord.supports_method("pylsp-rope", PREPARE_RENAME) is True

    def test_rename_provider_with_prepare_provider_false(self) -> None:
        server = _make_async_server_with_caps(
            "pylsp-rope",
            {"renameProvider": {"prepareProvider": False}},
        )
        coord = MultiServerCoordinator(
            servers={"pylsp-rope": server},
            dynamic_registry=_empty_registry(),
            catalog=_catalog_with(),
        )
        assert coord.supports_method("pylsp-rope", PREPARE_RENAME) is False

    def test_rename_itself_works_with_boolean_provider(self) -> None:
        """textDocument/rename is unaffected by the prepareRename special-case."""
        server = _make_async_server_with_caps("pylsp-rope", {"renameProvider": True})
        coord = MultiServerCoordinator(
            servers={"pylsp-rope": server},
            dynamic_registry=_empty_registry(),
            catalog=_catalog_with(),
        )
        assert coord.supports_method("pylsp-rope", RENAME) is True


# ---------------------------------------------------------------------------
# supports_kind — 3-tier (catalog → dynamic registry → codeActionKinds)
# ---------------------------------------------------------------------------


class TestSupportsKindTier1Catalog:
    """Tier 1: kind not in catalog → False immediately."""

    def test_kind_absent_from_catalog_returns_false(self) -> None:
        server = _make_async_server_with_caps(
            "pylsp-rope", {"codeActionProvider": True}
        )
        coord = MultiServerCoordinator(
            servers={"pylsp-rope": server},
            dynamic_registry=_empty_registry(),
            catalog=_catalog_with(),  # empty catalog
        )
        assert coord.supports_kind("python", "refactor.extract") is False

    def test_kind_in_catalog_for_different_language_returns_false(self) -> None:
        rec = _make_record("rust", "refactor.extract", "rust-analyzer")
        server = _make_async_server_with_caps(
            "rust-analyzer", {"codeActionProvider": True}
        )
        coord = MultiServerCoordinator(
            servers={"rust-analyzer": server},
            dynamic_registry=_empty_registry(),
            catalog=_catalog_with(rec),
        )
        assert coord.supports_kind("python", "refactor.extract") is False


class TestSupportsKindTier2DynamicRegistry:
    """Tier 2: catalog says yes; server must have textDocument/codeAction."""

    def test_dynamic_codeaction_registration_passes_tier2(self) -> None:
        rec = _make_record("python", "refactor.extract", "pylsp-rope")
        # Server has no static codeActionProvider, but dynamic registration present.
        server = _make_async_server_with_caps("pylsp-rope", {})
        registry = _registry_with("pylsp-rope", CODE_ACTION)
        coord = MultiServerCoordinator(
            servers={"pylsp-rope": server},
            dynamic_registry=registry,
            catalog=_catalog_with(rec),
        )
        # Tier 3: codeActionProvider absent → treated as "any kind" (True).
        assert coord.supports_kind("python", "refactor.extract") is True

    def test_no_codeaction_anywhere_returns_false(self) -> None:
        rec = _make_record("python", "refactor.extract", "pylsp-rope")
        server = _make_async_server_with_caps("pylsp-rope", {})  # no codeActionProvider
        coord = MultiServerCoordinator(
            servers={"pylsp-rope": server},
            dynamic_registry=_empty_registry(),
            catalog=_catalog_with(rec),
        )
        assert coord.supports_kind("python", "refactor.extract") is False


class TestSupportsKindTier3CodeActionKinds:
    """Tier 3: codeActionKinds list check per LSP 3.17."""

    def test_code_action_provider_true_accepts_any_kind(self) -> None:
        """Boolean True = no kind filter = any kind accepted per LSP 3.17."""
        rec = _make_record("python", "refactor.extract", "pylsp-rope")
        server = _make_async_server_with_caps(
            "pylsp-rope", {"codeActionProvider": True}
        )
        coord = MultiServerCoordinator(
            servers={"pylsp-rope": server},
            dynamic_registry=_empty_registry(),
            catalog=_catalog_with(rec),
        )
        assert coord.supports_kind("python", "refactor.extract") is True

    def test_code_action_provider_with_matching_kind(self) -> None:
        rec = _make_record("python", "refactor.extract", "pylsp-rope")
        server = _make_async_server_with_caps(
            "pylsp-rope",
            {"codeActionProvider": {"codeActionKinds": ["refactor", "refactor.extract"]}},
        )
        coord = MultiServerCoordinator(
            servers={"pylsp-rope": server},
            dynamic_registry=_empty_registry(),
            catalog=_catalog_with(rec),
        )
        assert coord.supports_kind("python", "refactor.extract") is True

    def test_code_action_provider_without_kind_returns_false(self) -> None:
        rec = _make_record("python", "refactor.extract", "pylsp-rope")
        server = _make_async_server_with_caps(
            "pylsp-rope",
            {"codeActionProvider": {"codeActionKinds": ["source.fixAll"]}},
        )
        coord = MultiServerCoordinator(
            servers={"pylsp-rope": server},
            dynamic_registry=_empty_registry(),
            catalog=_catalog_with(rec),
        )
        assert coord.supports_kind("python", "refactor.extract") is False

    def test_code_action_provider_empty_kinds_list_accepts_any(self) -> None:
        """Empty codeActionKinds list means 'any kind' per LSP 3.17."""
        rec = _make_record("python", "refactor.extract", "pylsp-rope")
        server = _make_async_server_with_caps(
            "pylsp-rope",
            {"codeActionProvider": {"codeActionKinds": []}},
        )
        coord = MultiServerCoordinator(
            servers={"pylsp-rope": server},
            dynamic_registry=_empty_registry(),
            catalog=_catalog_with(rec),
        )
        assert coord.supports_kind("python", "refactor.extract") is True

    def test_code_action_provider_absent_kinds_key_accepts_any(self) -> None:
        """codeActionKinds key absent in options dict = 'any kind'."""
        rec = _make_record("python", "refactor.extract", "pylsp-rope")
        server = _make_async_server_with_caps(
            "pylsp-rope",
            {"codeActionProvider": {}},
        )
        coord = MultiServerCoordinator(
            servers={"pylsp-rope": server},
            dynamic_registry=_empty_registry(),
            catalog=_catalog_with(rec),
        )
        assert coord.supports_kind("python", "refactor.extract") is True

    def test_catalog_in_constructor(self) -> None:
        """supports_kind uses the catalog injected at construction time."""
        rec = _make_record("python", "refactor.extract", "pylsp-rope")
        server = _make_async_server_with_caps(
            "pylsp-rope", {"codeActionProvider": True}
        )
        coord = MultiServerCoordinator(
            servers={"pylsp-rope": server},
            dynamic_registry=_empty_registry(),
            catalog=_catalog_with(rec),
        )
        assert coord.supports_kind("python", "refactor.extract") is True

    def test_supports_kind_returns_false_for_unknown_kind_in_catalog(self) -> None:
        """Kind X not in catalog → False regardless of server caps."""
        rec = _make_record("python", "refactor.extract", "pylsp-rope")
        server = _make_async_server_with_caps(
            "pylsp-rope", {"codeActionProvider": True}
        )
        coord = MultiServerCoordinator(
            servers={"pylsp-rope": server},
            dynamic_registry=_empty_registry(),
            catalog=_catalog_with(rec),
        )
        assert coord.supports_kind("python", "source.completely.unknown") is False


# ---------------------------------------------------------------------------
# DI: backward-compat — kwargs are optional (spec § 4.4.0)
# ---------------------------------------------------------------------------


class TestConstructorDI:
    def test_explicit_registry_and_catalog(self) -> None:
        coord = MultiServerCoordinator(
            servers={},
            dynamic_registry=_empty_registry(),
            catalog=_catalog_with(),
        )
        assert coord.servers == {}

    def test_omit_di_kwargs_uses_defaults(self) -> None:
        """No dynamic_registry= or catalog= keyword args — backward compat."""
        coord = MultiServerCoordinator(servers={})
        # Just confirm construction succeeds and _dynamic_registry is set.
        assert hasattr(coord, "_dynamic_registry")
        assert hasattr(coord, "_catalog")
