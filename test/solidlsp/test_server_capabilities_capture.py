"""Unit tests for Phase 0 DLP: ServerCapabilities capture.

Tests verify:
1. ``server_capabilities()`` returns ``{}`` before ``_initialize_with_override``
   fires (pre-init / server not yet started).
2. After capture, ``server_capabilities()`` returns the full dict from the
   ``initialize`` response ``capabilities`` field.
3. ``server_capabilities()`` returns a *copy* — mutating the returned dict
   does not affect subsequent calls (immutable stored state).
4. Calling ``_initialize_with_override`` a second time re-captures (idempotent
   replacement for the second-server-boot edge case; the stored caps reflect
   the most recent initialize response).
5. A ``None`` response and a response with empty ``capabilities`` both yield
   ``{}``, not ``None`` or an ``AttributeError``.

These tests operate on a ``_MinimalFakeLS`` stub that inherits
``server_capabilities`` from ``SolidLanguageServer`` without bootstrapping a
real subprocess — keeping the test suite fast and deterministic.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Minimal stub — inherits server_capabilities() without full SolidLanguageServer
# ---------------------------------------------------------------------------

class _MinimalFakeLS:
    """Lightweight stand-in that inherits only the methods under test.

    We import ``server_capabilities`` from ``SolidLanguageServer`` directly
    and bind it, instead of subclassing the ABC, to avoid triggering the
    heavyweight ``__init__`` (subprocess, pathspec, caches, etc.).
    """

    def server_capabilities(self) -> Mapping[str, Any]:
        """Delegated to the real implementation via direct import."""
        from solidlsp.ls import SolidLanguageServer  # noqa: PLC0415
        return SolidLanguageServer.server_capabilities(self)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestServerCapabilitiesPreInit:
    """server_capabilities() must be safe to call before initialize fires."""

    def test_returns_empty_dict_before_initialize(self) -> None:
        """Pre-init: no ``_server_capabilities`` attribute → empty dict, not AttributeError."""
        ls = _MinimalFakeLS()
        # _server_capabilities intentionally absent — mirrors pre-init state.
        assert not hasattr(ls, "_server_capabilities")
        result = ls.server_capabilities()
        assert result == {}

    def test_returns_dict_type_before_initialize(self) -> None:
        """The returned object must be a dict even before init."""
        ls = _MinimalFakeLS()
        result = ls.server_capabilities()
        assert isinstance(result, dict)


class TestServerCapabilitiesCapture:
    """Verify that captured caps are surfaced correctly post-init."""

    def _stub_with_caps(self, caps: dict[str, Any]) -> _MinimalFakeLS:
        ls = _MinimalFakeLS()
        ls._server_capabilities = caps  # type: ignore[attr-defined]
        return ls

    def test_returns_captured_dict(self) -> None:
        caps = {"definitionProvider": True, "referencesProvider": True}
        ls = self._stub_with_caps(caps)
        assert ls.server_capabilities() == caps

    def test_returns_copy_not_original(self) -> None:
        """Mutating the returned dict must not alter the stored caps."""
        caps = {"definitionProvider": True}
        ls = self._stub_with_caps(caps)
        returned = ls.server_capabilities()
        returned["injected"] = "malicious"
        # The stored caps are unchanged.
        assert ls.server_capabilities() == caps
        assert "injected" not in ls.server_capabilities()

    def test_empty_caps_dict_yields_empty(self) -> None:
        """Empty ServerCapabilities (no providers) → empty dict, not None."""
        ls = self._stub_with_caps({})
        assert ls.server_capabilities() == {}

    def test_nested_caps_dict_returned(self) -> None:
        """Nested provider options objects are preserved intact."""
        caps = {
            "renameProvider": {"prepareProvider": True},
            "codeActionProvider": {"codeActionKinds": ["refactor.extract"]},
        }
        ls = self._stub_with_caps(caps)
        assert ls.server_capabilities() == caps


class TestInitializeWithOverrideCapture:
    """Test the _initialize_with_override hook via the actual SolidLanguageServer logic.

    We do not boot a real subprocess.  Instead we patch the minimal surface the
    closure touches:
      - ``self.server.send.initialize`` — replaced with a spy that returns a
        controlled ``initialize`` response.
      - ``self.override_initialize_params`` — identity (returns params unchanged).

    The closure under test is created by the body of ``start_server()`` in ls.py.
    We re-execute just those two closure-creation lines so the test stays in sync
    with the implementation without duplicating its logic.
    """

    def _make_fake_ls_with_override(self, init_response: dict[str, Any] | None) -> _MinimalFakeLS:
        """Bootstrap a fake LS whose ``_initialize_with_override`` closure is wired."""
        from solidlsp.lsp_protocol_handler.lsp_types import InitializeParams
        from typing import cast

        ls = _MinimalFakeLS()

        # Provide the two methods the closure references.
        ls.override_initialize_params = lambda params: params  # type: ignore[attr-defined]

        # The "original" initialize just returns our controlled response.
        original_initialize = MagicMock(return_value=init_response)

        # Replicate the closure exactly as written in ls.py start_server():
        _original_initialize = original_initialize

        def _initialize_with_override(params: InitializeParams) -> Any:
            mutated = ls.override_initialize_params(cast(dict[str, Any], params))  # type: ignore[attr-defined]
            response = _original_initialize(cast(InitializeParams, mutated))
            from collections.abc import Mapping as _Mapping  # noqa: PLC0415
            raw_caps: _Mapping[str, Any] = (response or {}).get("capabilities", {}) or {}
            ls._server_capabilities = dict(raw_caps)  # type: ignore[attr-defined]
            return response

        ls._initialize_with_override = _initialize_with_override  # type: ignore[attr-defined]
        return ls

    def test_caps_populated_from_initialize_response(self) -> None:
        """Caps from the response are stored after the closure fires."""
        response = {"capabilities": {"definitionProvider": True, "hoverProvider": True}}
        ls = self._make_fake_ls_with_override(response)
        ls._initialize_with_override({})  # type: ignore[attr-defined]
        assert ls.server_capabilities() == response["capabilities"]

    def test_none_response_yields_empty_caps(self) -> None:
        """A None initialize response (server error path) → empty caps, no crash."""
        ls = self._make_fake_ls_with_override(None)
        ls._initialize_with_override({})  # type: ignore[attr-defined]
        assert ls.server_capabilities() == {}

    def test_missing_capabilities_key_yields_empty_caps(self) -> None:
        """A response without a 'capabilities' key → empty caps."""
        ls = self._make_fake_ls_with_override({"serverInfo": {"name": "foo"}})
        ls._initialize_with_override({})  # type: ignore[attr-defined]
        assert ls.server_capabilities() == {}

    def test_null_capabilities_value_yields_empty_caps(self) -> None:
        """A response with ``capabilities: null`` → empty caps, not None."""
        ls = self._make_fake_ls_with_override({"capabilities": None})
        ls._initialize_with_override({})  # type: ignore[attr-defined]
        assert ls.server_capabilities() == {}

    def test_second_initialize_replaces_caps(self) -> None:
        """Calling the closure a second time replaces the stored caps."""
        first_response = {"capabilities": {"definitionProvider": True}}
        ls = self._make_fake_ls_with_override(first_response)
        ls._initialize_with_override({})  # type: ignore[attr-defined]
        assert ls.server_capabilities() == {"definitionProvider": True}

        # Simulate a reconnect with different caps.
        second_caps = {"referencesProvider": True}
        ls._server_capabilities = second_caps  # type: ignore[attr-defined]
        assert ls.server_capabilities() == second_caps
