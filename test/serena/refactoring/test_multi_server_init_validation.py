"""Stage v0.2.0 follow-up #03b — ``MultiServerCoordinator.__init__`` validation.

The coordinator now refuses raw sync Stage 1E adapters at construction
time with a ``TypeError`` that names the offending server, the offending
method, and the ``_AsyncAdapter`` wrapper that fixes the gap. Without
this gate, ``await facade(**kwargs)`` inside ``broadcast`` raised the
cryptic ``TypeError: object list can't be used in 'await' expression``
deep in the fan-out (``multi_server.py:842-895``).

Closes WHAT-REMAINS.md §4 line 104 and stage-1h-results/PROGRESS.md:87.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from serena.refactoring.multi_server import MultiServerCoordinator
from serena.tools.scalpel_runtime import _AsyncAdapter


class _SyncOnly:
    """Bare sync adapter — exactly what trips ``await facade(**kwargs)``."""

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


def test_init_rejects_raw_sync_server() -> None:
    """Raw sync server → loud ``TypeError`` at construction, not in broadcast."""
    with pytest.raises(TypeError, match="_AsyncAdapter"):
        MultiServerCoordinator(servers={"ruff": _SyncOnly()})


def test_init_error_names_offending_server_and_method() -> None:
    with pytest.raises(TypeError) as excinfo:
        MultiServerCoordinator(
            servers={"basedpyright": _AsyncOnly(), "ruff": _SyncOnly()}
        )
    msg = str(excinfo.value)
    assert "'ruff'" in msg
    # Any one of the four awaited methods may surface first; the helper
    # reports the first hit. They're all on _SyncOnly, so any is valid.
    assert any(
        m in msg
        for m in (
            "request_code_actions",
            "resolve_code_action",
            "execute_command",
            "request_rename_symbol_edit",
        )
    )


def test_init_accepts_all_async_servers() -> None:
    """Stage 1D unit-test wiring (all-async fakes) must keep working."""
    coord = MultiServerCoordinator(
        servers={"pylsp-rope": _AsyncOnly(), "basedpyright": _AsyncOnly()}
    )
    assert set(coord.servers) == {"pylsp-rope", "basedpyright"}


def test_init_accepts_async_adapter_wrapped_sync_server() -> None:
    """Production wiring (sync ``SolidLanguageServer`` + ``_AsyncAdapter``)."""
    coord = MultiServerCoordinator(
        servers={"ruff": _AsyncAdapter(_SyncOnly())}
    )
    assert "ruff" in coord.servers


def test_init_accepts_magic_mock_servers() -> None:
    """v0.2.0-C ``find_symbol_position`` tests rely on ``MagicMock`` servers."""
    coord = MultiServerCoordinator(servers={"pylsp-rope": MagicMock()})
    assert "pylsp-rope" in coord.servers


def test_init_accepts_empty_pool() -> None:
    """Empty server dict is degenerate but legal — no methods to check."""
    coord = MultiServerCoordinator(servers={})
    assert coord.servers == {}
