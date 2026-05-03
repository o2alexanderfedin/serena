"""v1.5 Phase 2 — ``GenerateConstructorTool`` unit tests.

The Java e2e fixture (``playground/java/``) is **not yet created**, so
this Phase-2 test file ships **unit-only** with mocked jdtls responses.
The corresponding e2e is deferred to Phase 2.5 per spec § 4.4.

Spec source:
``docs/superpowers/specs/2026-04-29-lsp-feature-coverage-spec.md`` § 4.2.2.

Mirrors the test pattern used by ``test_stage_2a_t3_extract.py`` and the
``test_dispatcher_capability_gate`` suite: a synthetic ``MagicMock``
coordinator stubs ``supports_kind`` and ``merge_code_actions`` so the
facade can be exercised without booting jdtls.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from serena.tools.scalpel_facades import GenerateConstructorTool
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def _reset_runtime() -> Iterator[None]:
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def _make_tool(project_root: Path) -> GenerateConstructorTool:
    tool = GenerateConstructorTool.__new__(GenerateConstructorTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def _fake_jdtls_coord(supports: bool = True) -> MagicMock:
    coord = MagicMock()
    coord.supports_kind = MagicMock(return_value=supports)
    coord.merge_code_actions = AsyncMock(return_value=[
        MagicMock(
            action_id="jdtls:gen-ctor:1",
            title="Generate constructor",
            kind="source.generate.constructor",
            provenance="jdtls",
        ),
    ])
    coord.find_symbol_range = AsyncMock(return_value={
        "start": {"line": 0, "character": 0},
        "end": {"line": 5, "character": 1},
    })
    return coord


def test_generate_constructor_dispatches_source_generate_constructor(
    tmp_path: Path,
) -> None:
    """The facade dispatches ``source.generate.constructor`` against jdtls."""
    target = tmp_path / "Person.java"
    target.write_text(
        "class Person {\n"
        "    String name;\n"
        "    int age;\n"
        "}\n"
    )
    tool = _make_tool(tmp_path)
    coord = _fake_jdtls_coord(supports=True)
    seen: dict[str, object] = {}
    canned_actions = [
        MagicMock(
            action_id="jdtls:gen-ctor:1",
            title="Generate constructor",
            kind="source.generate.constructor",
            provenance="jdtls",
        ),
    ]

    async def _merge(**kwargs: object) -> list[MagicMock]:
        seen["only"] = kwargs["only"]
        seen["start"] = kwargs["start"]
        seen["end"] = kwargs["end"]
        return canned_actions

    coord.merge_code_actions = _merge

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ) as patched:
        out = tool.apply(
            file=str(target),
            class_name_path="Person",
            language="java",
        )

    payload = json.loads(out)
    assert payload["applied"] is True, payload
    assert seen["only"] == ["source.generate.constructor"]
    assert patched.call_args.kwargs["language"] == "java"


def test_generate_constructor_capability_not_available_when_unsupported(
    tmp_path: Path,
) -> None:
    """When jdtls does not advertise the kind, return CAPABILITY_NOT_AVAILABLE."""
    target = tmp_path / "Person.java"
    target.write_text("class Person {}\n")
    tool = _make_tool(tmp_path)
    coord = _fake_jdtls_coord(supports=False)
    coord.merge_code_actions = AsyncMock()

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(target),
            class_name_path="Person",
            language="java",
        )

    payload = json.loads(out)
    assert payload["status"] == "skipped"
    assert "lsp_does_not_support_source.generate.constructor" in payload["reason"]
    assert payload["language"] == "java"
    coord.merge_code_actions.assert_not_called()


def test_generate_constructor_dry_run_returns_preview_token(tmp_path: Path) -> None:
    """``preview=True`` returns a preview token without applying any edits."""
    target = tmp_path / "Person.java"
    target.write_text("class Person { String name; }\n")
    tool = _make_tool(tmp_path)
    coord = _fake_jdtls_coord(supports=True)

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(target),
            class_name_path="Person",
            language="java",
            preview=True,
        )

    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload["preview_token"] is not None
    assert payload["checkpoint_id"] is None


def test_generate_constructor_workspace_boundary_violation_blocked(
    tmp_path: Path,
) -> None:
    """Files outside the workspace are blocked by the boundary guard."""
    tool = _make_tool(tmp_path)
    out = tool.apply(
        file=str(tmp_path.parent / "Outside.java"),
        class_name_path="Outside",
        language="java",
    )
    payload = json.loads(out)
    assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"


def test_generate_constructor_no_actions_returns_symbol_not_found(
    tmp_path: Path,
) -> None:
    """When jdtls returns no code actions, surface SYMBOL_NOT_FOUND."""
    target = tmp_path / "Empty.java"
    target.write_text("class Empty {}\n")
    tool = _make_tool(tmp_path)
    coord = _fake_jdtls_coord(supports=True)
    coord.merge_code_actions = AsyncMock(return_value=[])

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(target),
            class_name_path="Empty",
            language="java",
        )

    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"
