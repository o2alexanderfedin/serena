"""Defensive runtime checks for ``MultiServerCoordinator``.

Stage 1D unit tests pass against ``_FakeServer`` (declares ``async def``
methods). Real Stage 1E adapters are sync; they MUST be wrapped in
``_AsyncAdapter`` (``serena.tools.scalpel_runtime``) before being handed
to ``MultiServerCoordinator``.

This module surfaces the contract loudly via ``__init__`` validation
rather than letting ``await facade(**kwargs)`` raise the cryptic
``TypeError: object list can't be used in 'await' expression`` deep
inside the broadcast fan-out (``multi_server.py:842-895``).

Closes WHAT-REMAINS.md §4 line 104 and the Stage 1H follow-up at
``stage-1h-results/PROGRESS.md:87``.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterable
from typing import Any
from unittest.mock import Mock

# ---------------------------------------------------------------------------
# Single source of truth for the four LSP facade method names that
# ``MultiServerCoordinator.broadcast`` awaits on each server. Both
# ``MultiServerCoordinator._AWAITED_SERVER_METHODS`` (gate input) and
# ``_AsyncAdapter._ASYNC_METHODS`` (which methods to wrap in a coroutine)
# derive from this tuple. Per project CLAUDE.md: "Each piece of
# information has one canonical location. Never duplicate across files."
# ---------------------------------------------------------------------------

AWAITED_SERVER_METHODS: tuple[str, ...] = (
    "request_code_actions",
    "resolve_code_action",
    "execute_command",
    "request_rename_symbol_edit",
)


def is_async_callable(obj: Any) -> bool:
    """Return ``True`` when ``obj`` can be safely ``await``\\ed by
    ``MultiServerCoordinator.broadcast``.

    The check is intentionally conservative — it returns ``True`` for
    anything we cannot **prove** to be sync. The cases:

    * ``async def`` function or bound method → ``True``
      (``inspect.iscoroutinefunction`` covers both).
    * Awaitable instance (already-running coroutine) → ``True``.
    * Callable object whose ``__call__`` is a coroutine function
      (e.g. the ``_AsyncAdapter._async_call`` closure) → ``True``.
    * ``unittest.mock.Mock`` instance carrying the explicit marker
      attribute ``_o2_async_callable=True`` → ``True``. The marker is
      an opt-in carve-out for tests that wire ``MagicMock`` servers
      into ``MultiServerCoordinator``; the test owns correctness for
      the marked attribute. Unmarked Mocks fall through to the
      ``callable`` branch and are rejected — preserving the loud
      TypeError guarantee for accidental Mock misuse in production.
    * Callable but not coroutine-function and not marked → ``False``
      (the only failure mode that warrants the loud TypeError).
    * Non-callable → ``False`` (treated as misuse).
    """
    if inspect.iscoroutinefunction(obj):
        return True
    if inspect.isawaitable(obj):
        return True
    # Mocks are opaque to introspection. Require explicit opt-in via the
    # ``_o2_async_callable=True`` marker attribute so that an accidental
    # Mock in production code still trips the loud TypeError gate. We
    # check ``__dict__`` directly because ``getattr`` on a ``MagicMock``
    # auto-creates a (truthy) child Mock for any missing attribute,
    # which would defeat the gate.
    if isinstance(obj, Mock) and obj.__dict__.get("_o2_async_callable") is True:
        return True
    if callable(obj):
        # Some callable objects implement ``__call__`` as ``async def``.
        call_attr = getattr(obj, "__call__", None)
        if call_attr is not None and inspect.iscoroutinefunction(call_attr):
            return True
    return False


def assert_servers_async_callable(
    servers: dict[str, Any],
    method_names: Iterable[str],
) -> None:
    """Raise ``TypeError`` if any server method is provably sync-only.

    Walks every (server_id, method_name) pair. If the method is absent
    on the server, the pair is skipped (legitimate omission — not all
    adapters implement every method). If the method is present but
    fails ``is_async_callable``, raise ``TypeError`` with a pointer to
    the ``_AsyncAdapter`` wrapper that resolves the gap.
    """
    for server_id, server in servers.items():
        for method_name in method_names:
            method = getattr(server, method_name, None)
            if method is None:
                continue
            if not is_async_callable(method):
                raise TypeError(
                    f"server {server_id!r} method {method_name!r} is not"
                    " async-callable; wrap with _AsyncAdapter"
                    " (serena.tools.scalpel_runtime) before constructing"
                    " MultiServerCoordinator. Without this wrapper,"
                    " `await facade(**kwargs)` inside `broadcast` raises"
                    " `TypeError: object <type> can't be used in 'await'"
                    " expression`."
                )


__all__ = [
    "AWAITED_SERVER_METHODS",
    "assert_servers_async_callable",
    "is_async_callable",
]
