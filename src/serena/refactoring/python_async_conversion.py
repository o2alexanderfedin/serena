"""v1.1 Stream 5 / Leaf 07 — `convert_to_async` helper.

Converts a sync Python function ``def f(...)`` into ``async def f(...)``,
optionally inserting ``await`` at every call site within the workspace.
The output is an LSP-spec ``WorkspaceEdit`` (``changes`` shape, keyed by
``file://`` URI) ready to flow through
``serena.tools.scalpel_facades._apply_workspace_edit_to_disk``.

Implementation is AST-based via the standard library ``ast`` module
(no third-party dep — ``libcst``/``astor`` are not in the project
dependency closure). Only the ``def <name>(`` token on the def line is
rewritten to ``async def <name>(`` so any decorators / leading comments
are preserved verbatim. Call sites are located with a second AST walk
and rewritten to ``await <name>(...)``; ``await`` is only injected at
call sites already inside an ``async def`` body (the recursive
close-over case in the spec — sync callers are left to the caller, who
sees ``unwrapped_call_sites`` in the result and decides whether to wrap
in ``asyncio.run(...)``).

Returns a tuple ``(workspace_edit, summary)`` where ``summary`` is a
small dict the facade surfaces in its ``RefactorResult.lsp_ops``
metadata (kept out of the WorkspaceEdit itself per the LSP spec).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any


_DEF_TOKEN_RE = re.compile(r"^(\s*)def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def convert_function_to_async(
    *,
    file: str,
    symbol: str,
    project_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a WorkspaceEdit that turns ``def symbol`` into ``async def symbol``.

    :param file: path (absolute or relative-to-``project_root``) of the
        Python file declaring ``symbol``.
    :param symbol: name of the function to convert.
    :param project_root: workspace root used to scope call-site rewrites.
    :returns: ``(workspace_edit, summary)``. ``summary`` carries
        ``{'def_line': int, 'await_call_sites': int,
        'unwrapped_call_sites': int}``.
    :raises FileNotFoundError: when ``file`` cannot be resolved.
    :raises ValueError: when ``symbol`` is not a top-level / nested
        ``def`` in ``file``.
    """
    target = _resolve(file, project_root)
    src = target.read_text(encoding="utf-8")
    tree = ast.parse(src)

    def_node = _find_def(tree, symbol)
    if def_node is None:
        raise ValueError(
            f"convert_function_to_async: symbol {symbol!r} is not a "
            f"`def` in {target}"
        )

    summary: dict[str, Any] = {
        "def_line": def_node.lineno,
        "await_call_sites": 0,
        "unwrapped_call_sites": 0,
    }

    file_uri = target.as_uri()
    changes: dict[str, list[dict[str, Any]]] = {file_uri: []}

    # Edit 1: rewrite the def line — `def NAME(` -> `async def NAME(`.
    src_lines = src.splitlines(keepends=True)
    def_line_idx = def_node.lineno - 1
    line_text = src_lines[def_line_idx].rstrip("\n").rstrip("\r")
    m = _DEF_TOKEN_RE.match(line_text)
    if m is None or m.group(2) != symbol:
        raise ValueError(
            f"convert_function_to_async: cannot locate `def {symbol}(` "
            f"on line {def_node.lineno} of {target}"
        )
    indent = m.group(1)
    new_def_prefix = f"{indent}async def {symbol}("
    old_def_prefix_end = m.end()
    changes[file_uri].append(
        {
            "range": {
                "start": {"line": def_line_idx, "character": 0},
                "end": {"line": def_line_idx, "character": old_def_prefix_end},
            },
            "newText": new_def_prefix,
        }
    )

    # Edit 2..N: insert `await ` at every call site whose enclosing def is
    # itself an `async def`. We compute the enclosing-def map first so we
    # know which call sites are already-async (recursive close-over).
    enclosing = _enclosing_async_map(tree)
    for call in _walk_calls(tree):
        if not _is_call_to(call, symbol):
            continue
        # Skip if the call is already `await NAME(...)` somewhere upstream
        # in source (avoid double-wrap). The Call node itself has no
        # `await`; the parent (an Expr/Assign whose value is the Call, or
        # an Await whose value is the Call) carries that.
        if call in _await_wrapped_calls(tree):
            continue
        host = enclosing.get(id(call))
        if host is None or not isinstance(host, ast.AsyncFunctionDef):
            summary["unwrapped_call_sites"] += 1
            continue
        # Insert `await ` at the call's start column.
        line_idx = call.lineno - 1
        col = call.col_offset
        changes[file_uri].append(
            {
                "range": {
                    "start": {"line": line_idx, "character": col},
                    "end": {"line": line_idx, "character": col},
                },
                "newText": "await ",
            }
        )
        summary["await_call_sites"] += 1

    return {"changes": changes}, summary


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve(file: str, project_root: Path) -> Path:
    candidate = Path(file)
    if not candidate.is_absolute():
        candidate = (project_root / candidate).resolve(strict=False)
    if not candidate.exists():
        raise FileNotFoundError(
            f"convert_function_to_async: file {file!r} not found "
            f"(resolved to {candidate})"
        )
    return candidate


def _find_def(tree: ast.AST, symbol: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == symbol:
            return node
    return None


def _walk_calls(tree: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)]


def _is_call_to(call: ast.Call, symbol: str) -> bool:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id == symbol
    if isinstance(func, ast.Attribute):
        return func.attr == symbol
    return False


def _enclosing_async_map(tree: ast.AST) -> dict[int, ast.AST]:
    """Return ``{id(call_node): enclosing_FunctionDef_or_None}``.

    ``None`` here means module level. The map is keyed by ``id`` so the
    AST node identity survives mutation-free traversal.
    """
    out: dict[int, ast.AST] = {}

    def visit(node: ast.AST, host: ast.AST | None) -> None:
        if isinstance(node, ast.Call):
            if host is not None:
                out[id(node)] = host
        new_host = host
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            new_host = node
        for child in ast.iter_child_nodes(node):
            visit(child, new_host)

    visit(tree, None)
    return out


def _await_wrapped_calls(tree: ast.AST) -> set[int]:
    """``id`` of every Call already wrapped in an ``Await`` node."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
            out.add(id(node.value))
    return out


__all__ = ["convert_function_to_async"]
