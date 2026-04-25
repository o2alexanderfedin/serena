"""T1 — multi-callback notification dispatch.

Proves: add_notification_listener(method, cb) -> handle; multiple listeners receive
the same payload; remove_notification_listener(handle) detaches; the legacy
on_notification(method, cb) still replaces the single primary listener
without affecting added listeners.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from solidlsp.ls_process import LanguageServerProcess


@pytest.fixture
def handler() -> LanguageServerProcess:
    h = LanguageServerProcess.__new__(LanguageServerProcess)
    h.on_notification_handlers = {}
    h.on_notification_listeners = {}
    h._listener_seq = 0
    h._listener_lock = threading.Lock()
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


def test_listener_exception_does_not_break_other_listeners(handler: LanguageServerProcess) -> None:
    bad = MagicMock(side_effect=RuntimeError("boom"))
    good = MagicMock()
    handler.add_notification_listener("$/progress", bad)
    handler.add_notification_listener("$/progress", good)
    handler._dispatch_notification("$/progress", {"v": 1})
    good.assert_called_once_with({"v": 1})  # good still fires
