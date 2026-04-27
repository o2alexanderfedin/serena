"""v1.1 Stream 5 / Leaf 07 — `annotate_return_type` helper.

Infers the return-type annotation for a Python function by querying
basedpyright's ``textDocument/inlayHint`` LSP request. The result is a
small ``WorkspaceEdit`` that inserts ``-> <Type>`` between the
function's closing ``)`` and the trailing ``:`` on the def line.

Status discriminator returned to the facade:

- ``"applied"`` — basedpyright produced a return-type hint and the edit
  was synthesized.
- ``"skipped"`` reason ``"already_annotated"`` — the def already has an
  explicit return type, no edit emitted.
- ``"skipped"`` reason ``"no_inferable_type"`` — basedpyright is
  available but the inlay-hint reply contained no return-type entry
  (e.g. ``unknown`` / no return statement) — caller annotates manually.
- ``"skipped"`` reason ``"basedpyright_unavailable"`` — the
  ``MultiServerCoordinator`` for the project has no basedpyright in the
  pool. Tests set the marker via the ``raise_on_unavailable`` arg so
  the facade can pivot to ``pytest.skip``.

The helper is pure-Python except for the ``basedpyright`` LSP call
which is delegated to the existing ``MultiServerCoordinator`` (Stage
1D). Resolution of the inlay-hint reply is purely string-based.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


def annotate_return_type(
    *,
    file: str,
    symbol: str,
    project_root: Path,
    inlay_hint_provider: Any | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Synthesize a single ``TextEdit`` inserting ``-> <Type>`` on a def.

    :param file: path of the Python file declaring ``symbol``.
    :param symbol: name of the function to annotate.
    :param project_root: workspace root.
    :param inlay_hint_provider: callable
        ``(file_uri, range_dict) -> list[InlayHint]`` typically bound to
        ``MultiServerCoordinator.fetch_inlay_hints``. Tests inject a
        stub. When ``None`` the helper short-circuits with the
        ``basedpyright_unavailable`` skip discriminator (no LSP boot
        attempt — by design, kept testable without a live server).
    :returns: ``(workspace_edit_or_none, status_dict)``.
    """
    target = _resolve(file, project_root)
    src = target.read_text(encoding="utf-8")
    tree = ast.parse(src)
    def_node = _find_def(tree, symbol)
    if def_node is None:
        return None, {
            "status": "failed",
            "reason": "symbol_not_found",
            "symbol": symbol,
        }

    # Already annotated? Skip per spec §Step 2.4.
    if def_node.returns is not None:
        return None, {
            "status": "skipped",
            "reason": "already_annotated",
            "symbol": symbol,
        }

    if inlay_hint_provider is None:
        return None, {
            "status": "skipped",
            "reason": "basedpyright_unavailable",
            "symbol": symbol,
        }

    # Compute the LSP range that covers the def signature line so the
    # provider returns inlay hints for the closing-paren region.
    file_uri = target.as_uri()
    lsp_range = {
        "start": {"line": def_node.lineno - 1, "character": 0},
        "end": {"line": def_node.lineno - 1, "character": 10_000},
    }
    hints = list(inlay_hint_provider(file_uri, lsp_range) or [])
    type_str = _pick_return_type_hint(hints)
    if type_str is None:
        return None, {
            "status": "skipped",
            "reason": "no_inferable_type",
            "symbol": symbol,
        }

    # Find the byte offset of the closing `)` and the trailing `:` on the
    # def line. We tolerate multi-line defs by scanning `src_lines` until
    # the matching `):` token is observed at depth 0.
    src_lines = src.splitlines(keepends=True)
    insertion = _locate_return_type_insertion(src_lines, def_node.lineno - 1)
    if insertion is None:
        return None, {
            "status": "failed",
            "reason": "could_not_locate_insertion_point",
            "symbol": symbol,
        }
    line_idx, col = insertion
    workspace_edit = {
        "changes": {
            file_uri: [
                {
                    "range": {
                        "start": {"line": line_idx, "character": col},
                        "end": {"line": line_idx, "character": col},
                    },
                    "newText": f" -> {type_str}",
                }
            ]
        }
    }
    return workspace_edit, {
        "status": "applied",
        "symbol": symbol,
        "inferred_type": type_str,
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _resolve(file: str, project_root: Path) -> Path:
    candidate = Path(file)
    if not candidate.is_absolute():
        candidate = (project_root / candidate).resolve(strict=False)
    if not candidate.exists():
        raise FileNotFoundError(
            f"annotate_return_type: file {file!r} not found "
            f"(resolved to {candidate})"
        )
    return candidate


def _find_def(tree: ast.AST, symbol: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol:
            return node
    return None


def _pick_return_type_hint(hints: list[Any]) -> str | None:
    """Pick the inlay-hint label that represents the return-type annotation.

    basedpyright surfaces return-type hints with ``kind=1`` (Type) and a
    label that begins with ``-> `` per the LSP spec. We accept either
    raw-LSP shape (dict with ``label``) or duck-typed objects with a
    ``.label`` attribute (so tests can pass simple namedtuples).
    """
    for h in hints:
        label = h.get("label") if isinstance(h, dict) else getattr(h, "label", None)
        if not isinstance(label, str):
            continue
        stripped = label.strip()
        if stripped.startswith("->"):
            # `-> int` -> `int`
            return stripped[2:].strip()
        # basedpyright sometimes emits just the type when paddingLeft=True;
        # treat any single-token type-shaped string preceded by `:` semantics
        # as a return-type label only when the kind is explicitly 1 (Type).
        kind = h.get("kind") if isinstance(h, dict) else getattr(h, "kind", None)
        if kind == 1 and stripped and not stripped.endswith(":"):
            position = h.get("position") if isinstance(h, dict) else getattr(h, "position", None)
            # Return-type hints sit at the end of the signature; arg
            # hints sit at the start. We can't fully disambiguate here
            # without column data, but a pragmatic fallback is to return
            # the label when basedpyright emitted exactly one Type hint.
            if position is not None and len(hints) == 1:
                return stripped.lstrip(":").strip()
    return None


def _locate_return_type_insertion(
    src_lines: list[str], def_line_idx: int,
) -> tuple[int, int] | None:
    """Find the (line, col) of the trailing ``:`` on a (possibly multi-line) def.

    Walks forward from ``def_line_idx`` tracking parenthesis depth so
    we ignore ``:`` characters inside type annotations, default
    expressions, etc. Returns ``(line, col)`` where ``col`` is the
    column of the colon — insertion of ``" -> Type"`` at this point
    yields the LSP TextEdit.
    """
    depth = 0
    for line_idx in range(def_line_idx, len(src_lines)):
        line = src_lines[line_idx]
        # Strip line ending for column math; inserts use the visible
        # column, not the trailing newline.
        for col, ch in enumerate(line.rstrip("\n").rstrip("\r")):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == ":" and depth == 0:
                return line_idx, col
    return None


__all__ = ["annotate_return_type"]
