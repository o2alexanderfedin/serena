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
    # The MCP server is invoked as `serena start-mcp-server` (verified entry
    # point in vendor/serena/src/serena/cli.py); the previous `serena-mcp`
    # invocation referenced a non-existent CLI entry. Per-language scoping
    # comes from the plugin's identity in marketplace.json — the MCP server
    # itself discovers from workspace, no `--language` flag needed.
    assert "serena" in srv["args"]
    assert "start-mcp-server" in srv["args"]


def test_mcp_json_for_python(fake_strategy_python) -> None:
    out = _render_mcp_json(fake_strategy_python)
    data = json.loads(out)
    assert "scalpel-python" in data["mcpServers"]
    srv = data["mcpServers"]["scalpel-python"]
    assert "serena" in srv["args"]
    assert "start-mcp-server" in srv["args"]


def test_mcp_json_is_deterministic(fake_strategy_rust) -> None:
    a = _render_mcp_json(fake_strategy_rust)
    b = _render_mcp_json(fake_strategy_rust)
    assert a == b
    assert a.endswith("\n")


# --- § 3.3 + § 3.4: correct engine URL (install-blockers Phase 0) -----------


def test_mcp_json_points_at_engine_repo_not_parent(fake_strategy_rust) -> None:
    """§ 3.3: .mcp.json must point at standalone engine, not vendor/serena subdir."""
    out = _render_mcp_json(fake_strategy_rust)
    data = json.loads(out)
    args = data["mcpServers"]["scalpel-rust"]["args"]
    source_idx = args.index("--from") + 1
    source = args[source_idx]
    assert "o2alexanderfedin/o2-scalpel-engine" in source
    assert "subdirectory" not in source


def test_mcp_json_no_o2services_in_url(fake_strategy_rust) -> None:
    """§ 3.4: o2services owner must not appear in any generated URL."""
    out = _render_mcp_json(fake_strategy_rust)
    assert "o2services" not in out


# --- § dedup-distinguisher: --server-name makes each plugin's args unique ----


def test_mcp_json_rust_has_server_name_arg(fake_strategy_rust) -> None:
    """Each plugin passes --server-name <id> so Claude Code plugin manager
    treats them as distinct MCP servers rather than deduplicating them."""
    out = _render_mcp_json(fake_strategy_rust)
    data = json.loads(out)
    args = data["mcpServers"]["scalpel-rust"]["args"]
    assert "--server-name" in args
    name_idx = args.index("--server-name") + 1
    assert args[name_idx] == "scalpel-rust"


def test_mcp_json_python_has_server_name_arg(fake_strategy_python) -> None:
    out = _render_mcp_json(fake_strategy_python)
    data = json.loads(out)
    args = data["mcpServers"]["scalpel-python"]["args"]
    assert "--server-name" in args
    name_idx = args.index("--server-name") + 1
    assert args[name_idx] == "scalpel-python"


def test_mcp_json_rust_and_python_args_differ(
    fake_strategy_rust, fake_strategy_python
) -> None:
    """Rust and Python plugins must produce different args so Claude Code
    plugin manager does not skip one as a duplicate of the other."""
    rust_out = json.loads(_render_mcp_json(fake_strategy_rust))
    python_out = json.loads(_render_mcp_json(fake_strategy_python))
    rust_args = rust_out["mcpServers"]["scalpel-rust"]["args"]
    python_args = python_out["mcpServers"]["scalpel-python"]["args"]
    assert rust_args != python_args
