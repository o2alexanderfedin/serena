"""T1 — multi-callback notification dispatch.

Proves: add_notification_listener(method, cb) -> handle; multiple listeners receive
the same payload; remove_notification_listener(handle) detaches; the legacy
on_notification(method, cb) still replaces the single primary listener
without affecting added listeners. Also pins the three pre-T1 dispatch
behaviors that _dispatch_notification preserves: asyncio.CancelledError
swallow, _is_shutting_down log gate, and the "Unhandled method" warning
for methods with neither primary nor listeners.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from unittest.mock import MagicMock

import pytest

from solidlsp.ls_process import LanguageServerProcess


@pytest.fixture
def handler() -> LanguageServerProcess:
    # Bypass __init__ on purpose: T1 listener subsystem is self-contained, and
    # constructing a real LanguageServerProcess here would require a child LSP
    # process. Manually populate only the fields the listener subsystem reads.
    h = LanguageServerProcess.__new__(LanguageServerProcess)
    h.on_notification_handlers = {}
    h.on_notification_listeners = {}
    h._listener_seq = 0
    h._listener_lock = threading.Lock()
    h._is_shutting_down = False
    return h


def test_add_and_remove_listener_receive_payload(handler: LanguageServerProcess) -> None:
    a = MagicMock()
    b = MagicMock()
    ha = handler.add_notification_listener("$/progress", a)
    handler.add_notification_listener("$/progress", b)
    handler._dispatch_notification("$/progress", {"value": 1})
    a.assert_called_once_with({"value": 1})
    b.assert_called_once_with({"value": 1})
    handler.remove_notification_listener(ha)
    handler._dispatch_notification("$/progress", {"value": 2})
    assert a.call_count == 1  # detached
    b.assert_called_with({"value": 2})


def test_legacy_on_notification_does_not_clobber_listeners(handler: LanguageServerProcess) -> None:
    listener = MagicMock()
    primary = MagicMock()
    handler.add_notification_listener("$/progress", listener)
    handler.on_notification("$/progress", primary)
    handler._dispatch_notification("$/progress", {"x": 1})
    listener.assert_called_once_with({"x": 1})
    primary.assert_called_once_with({"x": 1})


def test_listener_exception_does_not_break_other_listeners(
    handler: LanguageServerProcess, caplog: pytest.LogCaptureFixture
) -> None:
    bad = MagicMock(side_effect=RuntimeError("boom"))
    good = MagicMock()
    handler.add_notification_listener("$/progress", bad)
    handler.add_notification_listener("$/progress", good)
    with caplog.at_level(logging.ERROR, logger="solidlsp.ls_process"):
        handler._dispatch_notification("$/progress", {"v": 1})
    good.assert_called_once_with({"v": 1})  # good still fires
    assert any("Error in notification listener" in rec.getMessage() for rec in caplog.records)


def test_cancelled_error_in_listener_is_swallowed(handler: LanguageServerProcess) -> None:
    cancelled = MagicMock(side_effect=asyncio.CancelledError())
    handler.add_notification_listener("$/progress", cancelled)
    handler._dispatch_notification("$/progress", {"v": 1})  # must NOT raise


def test_cancelled_error_in_primary_is_swallowed(handler: LanguageServerProcess) -> None:
    cancelled = MagicMock(side_effect=asyncio.CancelledError())
    handler.on_notification("$/progress", cancelled)
    handler._dispatch_notification("$/progress", {"v": 1})  # must NOT raise


def test_shutdown_gate_silences_log(handler: LanguageServerProcess, caplog: pytest.LogCaptureFixture) -> None:
    handler._is_shutting_down = True
    bad = MagicMock(side_effect=RuntimeError("boom"))
    handler.add_notification_listener("$/progress", bad)
    with caplog.at_level(logging.ERROR, logger="solidlsp.ls_process"):
        handler._dispatch_notification("$/progress", {"v": 1})
    assert not any("Error in notification listener" in rec.getMessage() for rec in caplog.records)


def test_unhandled_method_warning(handler: LanguageServerProcess, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="solidlsp.ls_process"):
        handler._dispatch_notification("textDocument/foo", {})
    assert any("Unhandled method 'textDocument/foo'" in rec.getMessage() for rec in caplog.records)
