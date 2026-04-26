"""Stage 1J T3 — ``_render_mcp_json`` registers per-language MCP server."""

from __future__ import annotations

import json

from serena.refactoring.plugin_generator import _render_mcp_json


def test_mcp_json_has_named_server_for_rust(fake_strategy_rust) -> None:
    out = _render_mcp_json(fake_strategy_rust)
    data = json.loads(out)
    assert "mcpServers" in data
    assert "scalpel-rust" in data["mcpServers"]
    srv = data["mcpServers"]["scalpel-rust"]
    assert srv["command"] == "uvx"
    assert "--from" in srv["args"]
    assert "serena-mcp" in srv["args"]
    assert "--language" in srv["args"]
    assert "rust" in srv["args"]


def test_mcp_json_for_python(fake_strategy_python) -> None:
    out = _render_mcp_json(fake_strategy_python)
    data = json.loads(out)
    assert "scalpel-python" in data["mcpServers"]
    assert "python" in data["mcpServers"]["scalpel-python"]["args"]


def test_mcp_json_is_deterministic(fake_strategy_rust) -> None:
    a = _render_mcp_json(fake_strategy_rust)
    b = _render_mcp_json(fake_strategy_rust)
    assert a == b
    assert a.endswith("\n")
