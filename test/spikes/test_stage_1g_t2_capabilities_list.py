"""T3 — ScalpelCapabilitiesListTool: language filter, kind filter, descriptors."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def reset_runtime() -> Iterator[None]:
    from serena.tools.scalpel_runtime import ScalpelRuntime

    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def _build_tool():  # type: ignore[no-untyped-def]
    from unittest.mock import MagicMock

    from serena.tools.scalpel_primitives import ScalpelCapabilitiesListTool

    agent = MagicMock(name="SerenaAgent")
    return ScalpelCapabilitiesListTool(agent=agent)


def test_tool_name_is_scalpel_capabilities_list() -> None:
    from serena.tools.scalpel_primitives import ScalpelCapabilitiesListTool

    assert ScalpelCapabilitiesListTool.get_name_from_cls() == "scalpel_capabilities_list"


def test_apply_returns_json_array_of_descriptors() -> None:
    tool = _build_tool()
    raw = tool.apply()
    payload = json.loads(raw)
    assert isinstance(payload, list)
    if payload:
        for row in payload:
            assert set(row).issuperset({
                "capability_id", "title", "language",
                "kind", "source_server", "preferred_facade",
            })


def test_apply_filters_by_language() -> None:
    tool = _build_tool()
    raw = tool.apply(language="rust")
    payload = json.loads(raw)
    assert all(row["language"] == "rust" for row in payload)


def test_apply_filters_by_kind() -> None:
    tool = _build_tool()
    raw = tool.apply(filter_kind="refactor.extract")
    payload = json.loads(raw)
    assert all(row["kind"].startswith("refactor.extract") for row in payload)


def test_apply_unknown_language_returns_empty_list() -> None:
    tool = _build_tool()
    raw = tool.apply(language="cobol")  # type: ignore[arg-type]
    payload = json.loads(raw)
    assert payload == []
