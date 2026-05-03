"""Stage 1J T3 — ``_render_mcp_json`` registers per-language MCP server.

v2.0 wire-name cleanup (spec 2026-05-03 § 5.2): the ``mcpServers`` JSON-key
collapses to the constant ``"lsp"`` across all plugins so the wire format
becomes ``mcp__plugin_o2-scalpel-<lang>_lsp__<verb>``. The ``--server-name``
CLI arg stays per-language (``scalpel-<lang>``) so the dashboard ``pgrep``
pattern keeps working.
"""

from __future__ import annotations

import json

from serena.refactoring.plugin_generator import _render_mcp_json


def test_mcp_json_has_named_server_for_rust(fake_strategy_rust) -> None:
    out = _render_mcp_json(fake_strategy_rust)
    data = json.loads(out)
    assert "mcpServers" in data
    # v2.0: server JSON-key is the constant "lsp", not per-language.
    assert "lsp" in data["mcpServers"]
    srv = data["mcpServers"]["lsp"]
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
    assert "lsp" in data["mcpServers"]
    srv = data["mcpServers"]["lsp"]
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
    args = data["mcpServers"]["lsp"]["args"]
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
    """Each plugin passes ``--server-name <id>`` so Claude Code's plugin
    manager treats them as distinct MCP servers rather than deduplicating
    them. v2.0: this CLI arg is the per-language distinguisher (the
    JSON-key was collapsed to the constant "lsp")."""
    out = _render_mcp_json(fake_strategy_rust)
    data = json.loads(out)
    args = data["mcpServers"]["lsp"]["args"]
    assert "--server-name" in args
    name_idx = args.index("--server-name") + 1
    assert args[name_idx] == "scalpel-rust"


def test_mcp_json_python_has_server_name_arg(fake_strategy_python) -> None:
    out = _render_mcp_json(fake_strategy_python)
    data = json.loads(out)
    args = data["mcpServers"]["lsp"]["args"]
    assert "--server-name" in args
    name_idx = args.index("--server-name") + 1
    assert args[name_idx] == "scalpel-python"


def test_mcp_json_rust_and_python_args_differ(
    fake_strategy_rust, fake_strategy_python
) -> None:
    """Rust and Python plugins must produce different args so Claude Code
    plugin manager does not skip one as a duplicate of the other.

    v2.0 keeps this guarantee: ``--server-name`` is per-language even
    though the JSON-key now collapses to the constant ``"lsp"``."""
    rust_out = json.loads(_render_mcp_json(fake_strategy_rust))
    python_out = json.loads(_render_mcp_json(fake_strategy_python))
    rust_args = rust_out["mcpServers"]["lsp"]["args"]
    python_args = python_out["mcpServers"]["lsp"]["args"]
    assert rust_args != python_args


# --- § auto-project: --project-from-cwd activates the user's repo on launch -


def test_mcp_json_rust_passes_project_from_cwd(fake_strategy_rust) -> None:
    """Each plugin passes --project-from-cwd so the dashboard surfaces the
    active project + languages instead of 'None / N/A' until the agent
    manually calls activate_project."""
    out = _render_mcp_json(fake_strategy_rust)
    data = json.loads(out)
    args = data["mcpServers"]["lsp"]["args"]
    assert "--project-from-cwd" in args


def test_mcp_json_python_passes_project_from_cwd(fake_strategy_python) -> None:
    out = _render_mcp_json(fake_strategy_python)
    data = json.loads(out)
    args = data["mcpServers"]["lsp"]["args"]
    assert "--project-from-cwd" in args


# --- v2.0 wire-name cleanup: explicit assertions for the spec contract -----


def test_mcp_json_v2_0_server_key_is_constant_across_languages(
    fake_strategy_rust, fake_strategy_python
) -> None:
    """v2.0 spec § 5.2: server JSON-key must be the constant "lsp",
    independent of language, so the wire format becomes
    ``mcp__plugin_o2-scalpel-<lang>_lsp__<verb>``.
    """
    rust_out = json.loads(_render_mcp_json(fake_strategy_rust))
    python_out = json.loads(_render_mcp_json(fake_strategy_python))
    assert list(rust_out["mcpServers"].keys()) == ["lsp"]
    assert list(python_out["mcpServers"].keys()) == ["lsp"]


def test_mcp_json_v2_0_cli_server_name_diverges_from_json_key(
    fake_strategy_rust,
) -> None:
    """v2.0 spec § 5.2: the per-language CLI ``--server-name`` is
    intentionally distinct from the constant JSON-key. Together they keep
    (a) per-plugin args-array uniqueness for Claude Code's deduper and
    (b) the dashboard ``pgrep -f "--server-name scalpel-<lang>"`` pattern
    working unchanged.
    """
    out = json.loads(_render_mcp_json(fake_strategy_rust))
    json_keys = list(out["mcpServers"].keys())
    args = out["mcpServers"]["lsp"]["args"]
    name_idx = args.index("--server-name") + 1
    cli_name = args[name_idx]
    assert json_keys == ["lsp"]
    assert cli_name == "scalpel-rust"
    assert json_keys[0] != cli_name
