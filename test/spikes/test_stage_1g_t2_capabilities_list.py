"""T3 — CapabilitiesListTool: language filter, kind filter, descriptors."""

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

    from serena.tools.scalpel_primitives import CapabilitiesListTool

    agent = MagicMock(name="SerenaAgent")
    return CapabilitiesListTool(agent=agent)


def test_tool_name_is_scalpel_capabilities_list() -> None:
    from serena.tools.scalpel_primitives import CapabilitiesListTool

    assert CapabilitiesListTool.get_name_from_cls() == "capabilities_list"


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


# --- new tests: _ensure_supported_language dynamic registry check ----------


def test_ensure_supported_language_accepts_stream6_languages() -> None:
    """All Stream 6 languages are accepted without raising."""
    from serena.tools.scalpel_primitives import _ensure_supported_language

    for lang in ("typescript", "go", "cpp", "java", "lean", "smt2", "prolog", "problog"):
        result = _ensure_supported_language(lang)
        assert result == lang, f"Expected {lang!r} returned unchanged, got {result!r}"


def test_ensure_supported_language_raises_with_helpful_message() -> None:
    """Unregistered language raises ValueError listing registered languages."""
    import pytest
    from serena.tools.scalpel_primitives import _ensure_supported_language

    with pytest.raises(ValueError, match="No strategy registered for language 'cobol'"):
        _ensure_supported_language("cobol")

    # Error message must include some of the registered languages.
    try:
        _ensure_supported_language("cobol")
    except ValueError as exc:
        message = str(exc)
        assert "rust" in message
        assert "python" in message
        assert "registered:" in message
