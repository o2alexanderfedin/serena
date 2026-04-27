"""Unit coverage for attach_apply_source / get_apply_source helpers."""
from __future__ import annotations

import inspect

from serena.tools.facade_support import (
    attach_apply_source,
    get_apply_source,
)


class _SampleTool:
    def apply(self, x: int) -> int:
        # workspace_boundary_guard(  # marker
        return x + 1


def test_attach_apply_source_captures_inspect_getsource_once() -> None:
    attach_apply_source(_SampleTool)
    captured = getattr(_SampleTool.apply, "__wrapped_source__", None)
    assert isinstance(captured, str) and captured
    assert captured == inspect.getsource(_SampleTool.apply)


def test_get_apply_source_prefers_captured_attribute() -> None:
    attach_apply_source(_SampleTool)
    _SampleTool.apply.__wrapped_source__ = "SENTINEL_CAPTURED_VALUE"  # type: ignore[attr-defined]
    assert get_apply_source(_SampleTool) == "SENTINEL_CAPTURED_VALUE"


def test_get_apply_source_falls_back_to_inspect_getsource() -> None:
    class _UnattachedTool:
        def apply(self) -> None:
            return None

    assert "def apply" in get_apply_source(_UnattachedTool)
