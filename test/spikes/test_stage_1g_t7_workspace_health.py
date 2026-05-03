"""T7 — WorkspaceHealthTool: per-language ServerHealth aggregate."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _reset_runtime() -> Iterator[None]:
    from serena.tools.scalpel_runtime import ScalpelRuntime

    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def _build_tool(project_root: Path):  # type: ignore[no-untyped-def]
    from serena.tools.scalpel_primitives import WorkspaceHealthTool

    agent = MagicMock(name="SerenaAgent")
    agent.get_active_project_or_raise.return_value = MagicMock(
        project_root=str(project_root),
    )
    return WorkspaceHealthTool(agent=agent)


def test_tool_name_is_scalpel_workspace_health() -> None:
    from serena.tools.scalpel_primitives import WorkspaceHealthTool

    assert WorkspaceHealthTool.get_name_from_cls() == "workspace_health"


def test_apply_returns_workspace_health_shape(tmp_path: Path) -> None:
    tool = _build_tool(tmp_path)
    raw = tool.apply()
    payload = json.loads(raw)
    assert "project_root" in payload
    assert "languages" in payload
    assert isinstance(payload["languages"], dict)


def test_apply_uses_explicit_project_root_when_provided(tmp_path: Path) -> None:
    """When project_root is passed, it overrides the agent's active project."""
    other = tmp_path / "explicit_root"
    other.mkdir()
    tool = _build_tool(tmp_path)
    raw = tool.apply(project_root=str(other))
    payload = json.loads(raw)
    assert Path(payload["project_root"]).expanduser().resolve() == other.resolve()


def test_apply_per_language_indexing_state_is_one_of_four(tmp_path: Path) -> None:
    tool = _build_tool(tmp_path)
    raw = tool.apply()
    payload = json.loads(raw)
    legal = {"indexing", "ready", "failed", "not_started"}
    for lang_block in payload["languages"].values():
        assert lang_block["indexing_state"] in legal


def test_apply_carries_capability_catalog_hash(tmp_path: Path) -> None:
    tool = _build_tool(tmp_path)
    raw = tool.apply()
    payload = json.loads(raw)
    # CapabilityCatalog.hash() doesn't exist in current Stage 1F build —
    # the tool falls back to "" so downstream type stays str.
    for lang_block in payload["languages"].values():
        assert isinstance(lang_block["capability_catalog_hash"], str)


def test_apply_includes_pool_stats_per_language(tmp_path: Path) -> None:
    """ServerHealth rows include server_id/version/pid/rss_mb fields."""
    tool = _build_tool(tmp_path)
    raw = tool.apply()
    payload = json.loads(raw)
    for lang_block in payload["languages"].values():
        for srv in lang_block["servers"]:
            assert "server_id" in srv
            assert "version" in srv
            assert "pid" in srv
            assert "rss_mb" in srv
