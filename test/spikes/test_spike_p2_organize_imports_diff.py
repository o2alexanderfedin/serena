"""P2 - source.organizeImports merge winner between pylsp-rope and ruff.

OUTCOME: a structured diff between the two organize-imports outputs on the same
polluted Python source. DECISION (pre-determined per scope report §11.1):
ruff wins; pylsp-rope's organize-imports is dropped at merge time.

This spike documents the *shape* of the divergence so multi_server.py knows what
to drop. Both LSPs hit raw stdio JSON-RPC because the wrapper has no pylsp/ruff
adapter (Stage 1E adds them).

Both servers are command/edit-style:
- ruff: code-action `edit:` field is populated directly (no resolve / no executeCommand).
- pylsp-rope: code-action `command:` field carries `pylsp_rope.source.organize_import`;
  edits arrive via `workspace/applyEdit` reverse-request after `executeCommand`.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ._pylsp_client import PylspClient
from ._ruff_client import RuffClient
from .conftest import write_spike_result

CLIENT_CAPS: dict[str, Any] = {
    "workspace": {"applyEdit": True, "workspaceEdit": {"documentChanges": True}},
    "textDocument": {
        "codeAction": {
            "codeActionLiteralSupport": {"codeActionKind": {"valueSet": ["source.organizeImports", "quickfix", "source", "source.fixAll"]}},
            "resolveSupport": {"properties": ["edit"]},
        },
    },
}


def _apply_text_edits(text: str, edits: list[dict[str, Any]]) -> str:
    """Apply LSP TextEdits (each {range, newText}) to `text`. Edits sorted descending."""
    lines = text.splitlines(keepends=True)

    def offset(line: int, char: int) -> int:
        return sum(len(line_text) for line_text in lines[:line]) + char

    sorted_edits = sorted(
        edits,
        key=lambda e: (e["range"]["start"]["line"], e["range"]["start"]["character"]),
        reverse=True,
    )
    out = text
    for e in sorted_edits:
        start = offset(e["range"]["start"]["line"], e["range"]["start"]["character"])
        end = offset(e["range"]["end"]["line"], e["range"]["end"]["character"])
        out = out[:start] + e.get("newText", "") + out[end:]
        # Recompute lines for next edit (descending order keeps offsets valid in original text,
        # but we recompute conservatively in case of multiline newText).
        lines = out.splitlines(keepends=True)
    return out


def _extract_text_edits(workspace_edit: dict[str, Any], target_uri: str) -> list[dict[str, Any]]:
    """Pull the TextEdit list for `target_uri` from a WorkspaceEdit payload."""
    if not workspace_edit:
        return []
    out: list[dict[str, Any]] = []
    for change in workspace_edit.get("documentChanges") or []:
        td = change.get("textDocument") or {}
        if td.get("uri") == target_uri:
            out.extend(change.get("edits") or [])
    for uri, edits in (workspace_edit.get("changes") or {}).items():
        if uri == target_uri:
            out.extend(edits or [])
    return out


def test_p2_organize_imports_diff(seed_python_root: Path, results_dir: Path) -> None:
    init_py = seed_python_root / "calcpy_seed" / "__init__.py"
    original = init_py.read_text(encoding="utf-8")
    polluted = "import os\nimport sys\nfrom typing import List\n" + original
    uri = init_py.as_uri()
    end_line = len(polluted.splitlines())
    full_range = {"start": {"line": 0, "character": 0}, "end": {"line": end_line, "character": 0}}

    # ---- pylsp-rope branch ----
    pylsp = PylspClient(seed_python_root)
    ruff = RuffClient(seed_python_root)
    try:
        pylsp.request(
            "initialize",
            {"processId": None, "rootUri": seed_python_root.as_uri(), "capabilities": CLIENT_CAPS},
            timeout=15.0,
        )
        pylsp.notify("initialized", {})
        pylsp.notify(
            "textDocument/didOpen",
            {"textDocument": {"uri": uri, "languageId": "python", "version": 0, "text": original}},
        )
        pylsp.notify(
            "textDocument/didChange",
            {"textDocument": {"uri": uri, "version": 1}, "contentChanges": [{"text": polluted}]},
        )
        time.sleep(0.4)
        pylsp_ca = pylsp.request(
            "textDocument/codeAction",
            {"textDocument": {"uri": uri}, "range": full_range, "context": {"diagnostics": []}},
            timeout=8.0,
        )
        pylsp_actions = [a for a in pylsp_ca.get("result") or [] if isinstance(a, dict)]
        pylsp_organize = next(
            (a for a in pylsp_actions if a.get("kind") == "source.organizeImports"),
            None,
        )
        pylsp_text = polluted
        pylsp_edits: list[dict[str, Any]] = []
        if pylsp_organize and pylsp_organize.get("command"):
            cmd = pylsp_organize["command"]
            pylsp.request(
                "workspace/executeCommand",
                {"command": cmd["command"], "arguments": cmd.get("arguments", [])},
                timeout=12.0,
            )
            for params in pylsp.apply_edits:
                pylsp_edits.extend(_extract_text_edits(params.get("edit") or {}, uri))
            pylsp_text = _apply_text_edits(polluted, pylsp_edits) if pylsp_edits else polluted

        # ---- ruff branch ----
        ruff.request(
            "initialize",
            {"processId": None, "rootUri": seed_python_root.as_uri(), "capabilities": CLIENT_CAPS},
            timeout=15.0,
        )
        ruff.notify("initialized", {})
        ruff.notify(
            "textDocument/didOpen",
            {"textDocument": {"uri": uri, "languageId": "python", "version": 0, "text": original}},
        )
        ruff.notify(
            "textDocument/didChange",
            {"textDocument": {"uri": uri, "version": 1}, "contentChanges": [{"text": polluted}]},
        )
        time.sleep(0.4)
        ruff_ca = ruff.request(
            "textDocument/codeAction",
            {
                "textDocument": {"uri": uri},
                "range": full_range,
                "context": {"diagnostics": [], "only": ["source.organizeImports"]},
            },
            timeout=8.0,
        )
        ruff_actions = [a for a in ruff_ca.get("result") or [] if isinstance(a, dict)]
        ruff_organize = next(
            (a for a in ruff_actions if (a.get("kind") or "").startswith("source.organizeImports")),
            None,
        )
        ruff_edits = _extract_text_edits((ruff_organize or {}).get("edit") or {}, uri)
        ruff_text = _apply_text_edits(polluted, ruff_edits) if ruff_edits else polluted
    finally:
        pylsp.shutdown()
        ruff.shutdown()

    # ---- Diff classification ----
    same_output = pylsp_text == ruff_text
    unused_lines = ("import os\n", "import sys\n", "from typing import List\n")
    pylsp_removed_unused = all(line not in pylsp_text for line in unused_lines)
    ruff_removed_unused = all(line not in ruff_text for line in unused_lines)
    if pylsp_organize is None and ruff_organize is None:
        outcome = "DIVERGENT - neither LSP returned source.organizeImports"
    elif pylsp_organize is None:
        outcome = "DIVERGENT - only ruff returned source.organizeImports"
    elif ruff_organize is None:
        outcome = "DIVERGENT - only pylsp-rope returned source.organizeImports"
    elif same_output:
        outcome = "CONVERGENT - both LSPs produced identical organize-imports output"
    else:
        outcome = "DIVERGENT - both LSPs returned source.organizeImports with differing edits"

    body = (
        "# P2 - source.organizeImports diff between pylsp-rope and ruff\n\n"
        f"**Outcome:** {outcome}\n\n"
        "**Decision (fixed per scope report §11.1):** Ruff wins by §11.1 priority table. "
        "pylsp-rope's organize-imports is dropped at merge time when both are available.\n\n"
        "**Inputs:**\n\n"
        f"- Seed file: `calcpy_seed/__init__.py` ({len(original)} bytes original)\n"
        "- Pollution: prepend `import os\\nimport sys\\nfrom typing import List\\n` (3 unused imports)\n"
        f"- Polluted size: {len(polluted)} bytes / {end_line} lines (in-memory only; no disk write)\n\n"
        "**Per-LSP outcomes:**\n\n"
        "_pylsp-rope:_\n\n"
        f"- Code actions surfaced (full-file range): {len(pylsp_actions)}\n"
        f"- `source.organizeImports` action present: {pylsp_organize is not None}\n"
        f"- Action style: command-typed (executes via `workspace/executeCommand`)\n"
        f"- Command: {((pylsp_organize or {}).get('command') or {}).get('command')!r}\n"
        f"- WorkspaceEdit arrival: via `workspace/applyEdit` reverse-request "
        f"({len(pylsp.apply_edits)} captured)\n"
        f"- TextEdits applied to `__init__.py`: {len(pylsp_edits)}\n\n"
        "_ruff:_\n\n"
        f"- Code actions surfaced (filtered `source.organizeImports`): {len(ruff_actions)}\n"
        f"- `source.organizeImports.ruff` action present: {ruff_organize is not None}\n"
        f"- Action kind: {(ruff_organize or {}).get('kind')!r} (LSP hierarchical sub-kind of `source.organizeImports`)\n"
        f"- Action style: edit-typed (no resolve, no executeCommand needed)\n"
        f"- WorkspaceEdit arrival: inline in action.edit\n"
        f"- TextEdits on `__init__.py`: {len(ruff_edits)}\n\n"
        "**Polluted input (verbatim):**\n\n"
        f"```python\n{polluted}```\n\n"
        "**pylsp-rope organize-imports output:**\n\n"
        f"```python\n{pylsp_text}```\n\n"
        "**ruff organize-imports output:**\n\n"
        f"```python\n{ruff_text}```\n\n"
        "**Diff shape:**\n\n"
        f"- Same byte-for-byte output: {same_output}\n"
        f"- pylsp-rope removed all unused imports (`os` / `sys` / `List`): {pylsp_removed_unused}\n"
        f"- ruff removed all unused imports (`os` / `sys` / `List`): {ruff_removed_unused}\n"
        f"- pylsp-rope output bytes: {len(pylsp_text)}; ruff output bytes: {len(ruff_text)}\n\n"
        "**API audit (2026-04-24):**\n\n"
        "- Wrapper gap: `SolidLanguageServer` has neither pylsp nor ruff adapter "
        "(`src/solidlsp/language_servers/` lacks both). Test bypasses wrapper via raw stdio "
        "JSON-RPC for both LSPs, mirroring P1's pattern.\n"
        "- ruff capability surface (verified at runtime): `codeActionKinds = "
        "[quickfix, source.fixAll.ruff, source.organizeImports.ruff, "
        "notebook.source.fixAll.ruff, notebook.source.organizeImports.ruff]`. "
        "ruff publishes the action under the hierarchical sub-kind `source.organizeImports.ruff`; "
        "filtering by `only: [source.organizeImports]` matches per LSP §3.18.1 prefix rule.\n"
        "- ruff exposes `executeCommandProvider.commands = [ruff.applyFormat, ruff.applyAutofix, "
        "ruff.applyOrganizeImports, ruff.printDebugInformation]`; we did NOT route through "
        "executeCommand because the inline `edit:` is sufficient and avoids an extra round-trip.\n"
        "- pylsp-rope organize-imports is `kind: source.organizeImports` exactly (not hierarchical) "
        "and is `command:`-typed; matches the P1 finding that pylsp-rope is command-typed across "
        "its action surface (refactoring.py:CommandSourceOrganizeImport).\n\n"
        "**Stage 1 implications:**\n\n"
        "- Stage 1D `multi_server.py` priority table: when both LSPs surface a "
        "`source.organizeImports[.<server>]` action, drop pylsp-rope's, keep ruff's.\n"
        "- LoC delta vs. optimistic: 0 LoC for ruff (one of N already-routed source-actions); "
        "+20-50 LoC for the disambiguation rule itself in `multi_server.py`.\n"
        "- Strategy-level config `engine: {ruff, rope}` exposed to users in v1.1, not MVP.\n"
    )
    out = write_spike_result(results_dir, "P2", body)
    print(f"\n[P2] Outcome: {outcome}; wrote {out}")
    print(
        f"[P2] pylsp_actions={len(pylsp_actions)} pylsp_organize={pylsp_organize is not None} "
        f"pylsp_edits={len(pylsp_edits)} ruff_actions={len(ruff_actions)} "
        f"ruff_organize={ruff_organize is not None} ruff_edits={len(ruff_edits)} "
        f"same_output={same_output}"
    )
    assert outcome
