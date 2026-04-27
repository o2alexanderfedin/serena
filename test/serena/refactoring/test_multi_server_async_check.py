"""Stage v0.2.0 follow-up #03a — async-callable detector unit tests.

Covers the primitive ``is_async_callable`` detector and the
``assert_servers_async_callable`` multi-server gate. The
``MultiServerCoordinator.__init__`` integration tests live in
``test_multi_server_init_validation.py`` (commit 03b).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from serena.refactoring._async_check import (
    assert_servers_async_callable,
    is_async_callable,
)
from serena.tools.scalpel_runtime import _AsyncAdapter


class _SyncOnly:
    """A bare sync adapter — exactly what trips ``await facade(**kwargs)``."""

    def request_code_actions(self, **_: Any) -> list[Any]:
        return []

    def resolve_code_action(self, action: dict[str, Any]) -> dict[str, Any]:
        return action

    def execute_command(self, name: str, args: list[Any] | None = None) -> Any:
        del name, args
        return None

    def request_rename_symbol_edit(self, **_: Any) -> dict[str, Any] | None:
        return None


class _AsyncOnly:
    """Mirrors the Stage 1D ``_FakeServer`` shape — async on the wire."""

    async def request_code_actions(self, **_: Any) -> list[Any]:
        return []

    async def resolve_code_action(self, action: dict[str, Any]) -> dict[str, Any]:
        return action

    async def execute_command(self, name: str, args: list[Any] | None = None) -> Any:
        del name, args
        return None

    async def request_rename_symbol_edit(self, **_: Any) -> dict[str, Any] | None:
        return None


# ---------------------------------------------------------------------------
# is_async_callable — primitive detector unit tests
# ---------------------------------------------------------------------------


def test_sync_method_is_not_async_callable() -> None:
    assert is_async_callable(_SyncOnly().request_code_actions) is False


def test_async_method_is_async_callable() -> None:
    assert is_async_callable(_AsyncOnly().request_code_actions) is True


def test_plain_function_async_def_is_async_callable() -> None:
    async def coro_fn() -> None:
        return None

    assert is_async_callable(coro_fn) is True


def test_plain_function_sync_def_is_not_async_callable() -> None:
    def sync_fn() -> None:
        return None

    assert is_async_callable(sync_fn) is False


def test_async_adapter_wraps_sync_server_into_async_callable() -> None:
    """The ``_AsyncAdapter`` from Stage 2A must surface as async-callable.

    Without this, the production wiring at ``scalpel_runtime._spawn_*``
    would be incorrectly flagged by the new defensive check.
    """
    adapter = _AsyncAdapter(_SyncOnly())
    assert is_async_callable(adapter.request_code_actions) is True


def test_magic_mock_is_treated_as_async_callable() -> None:
    """``MagicMock`` test doubles must NOT be rejected.

    ``test_v0_2_0_c_find_symbol_position.py`` constructs coordinators from
    ``MagicMock`` instances; rejecting them would break Stage 1D / v0.2.0-C
    unit tests. The check only rejects *definitely-sync* callables.
    """
    mock = MagicMock()
    assert is_async_callable(mock.request_code_actions) is True


# ---------------------------------------------------------------------------
# assert_servers_async_callable — multi-server gate
# ---------------------------------------------------------------------------


def test_assert_servers_raises_on_sync_member() -> None:
    with pytest.raises(TypeError, match="not async-callable"):
        assert_servers_async_callable(
            {"basedpyright": _AsyncOnly(), "ruff": _SyncOnly()},
            method_names=("request_code_actions",),
        )


def test_assert_servers_passes_on_all_async() -> None:
    assert_servers_async_callable(
        {"a": _AsyncOnly(), "b": _AsyncOnly()},
        method_names=("request_code_actions",),
    )


def test_assert_servers_passes_on_async_adapter_wrapped_sync() -> None:
    """``_AsyncAdapter`` is the production wrapper; it must satisfy the gate."""
    assert_servers_async_callable(
        {
            "ruff": _AsyncAdapter(_SyncOnly()),
            "basedpyright": _AsyncAdapter(_SyncOnly()),
        },
        method_names=(
            "request_code_actions",
            "resolve_code_action",
            "execute_command",
            "request_rename_symbol_edit",
        ),
    )


def test_assert_servers_skips_missing_methods() -> None:
    """Missing methods aren't a contract violation per se.

    Some adapters legitimately omit methods (e.g. a rust-only server has
    no ``configure_python_path``). The gate enforces async-ness for the
    methods that DO exist; absence is fine.
    """

    class _PartialAsync:
        async def request_code_actions(self, **_: Any) -> list[Any]:
            return []

    assert_servers_async_callable(
        {"partial": _PartialAsync()},
        method_names=(
            "request_code_actions",
            "resolve_code_action",  # absent — should be skipped, not raised
            "execute_command",
            "request_rename_symbol_edit",
        ),
    )


def test_assert_servers_message_names_offending_server_and_method() -> None:
    with pytest.raises(TypeError) as excinfo:
        assert_servers_async_callable(
            {"ruff": _SyncOnly()},
            method_names=("request_code_actions",),
        )
    msg = str(excinfo.value)
    assert "'ruff'" in msg
    assert "'request_code_actions'" in msg
    assert "_AsyncAdapter" in msg


