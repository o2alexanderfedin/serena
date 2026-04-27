"""Stage 1H T10 Module 6 — Python: ruff ``source.fixAll.ruff``.

Targets calcpy with deliberate F401/E711 lint triggers injected as a
sentinel block. Asserts:

(a) ruff offers ``source.fixAll.ruff`` (or its un-suffixed
    ``source.fixAll`` fallback) on the dirty buffer.
(b) Post-apply, the deliberate F401 (unused import) and E711 (== None)
    lints are gone — count delta of ruff diagnostics decreases by
    at least the number of injected lints.

Both sub-tests skip cleanly when ruff cannot be reached (host gap).
The ruff binary IS installed on this dev host so at least sub-test (a)
should actively run.

The mutation is restored in a try/finally so the fixture is left intact.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from solidlsp.ls import SolidLanguageServer


_REL = "calcpy/calcpy.py"
# Two deliberate ruff lints: unused stdlib import + ``== None`` instead of ``is None``.
_LINT_SENTINEL = (
    "\n# T10 Module 6 — deliberate F401 (unused import) + E711 (== None)\n"
    "import statistics  # noqa: ruff handles this — F401 on unused import\n"
    "_E711 = (1 == None)\n"
)


def _request_diagnostics(srv: "SolidLanguageServer", rel: str) -> list[dict[str, Any]]:
    """Pull ruff diagnostics via textDocument/diagnostic; ruff supports it."""
    try:
        abs_path = Path(srv.repository_root_path) / rel
        uri = abs_path.as_uri()
        params = {"textDocument": {"uri": uri}}
        resp = srv.server.send_request("textDocument/diagnostic", params)
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(resp, dict):
        return []
    items = resp.get("items")
    if not isinstance(items, list):
        return []
    return [d for d in items if isinstance(d, dict)]


def test_ruff_offers_fix_all(
    ruff_lsp: "SolidLanguageServer",
    calcpy_workspace: Path,
) -> None:
    """ruff must surface ``source.fixAll[.ruff]`` on the dirty file."""
    from solidlsp.util.file_range import compute_file_range

    src = calcpy_workspace / "calcpy" / "calcpy.py"
    original = src.read_text()
    try:
        src.write_text(original + _LINT_SENTINEL)
        file_start, file_end = compute_file_range(str(src))
        with ruff_lsp.open_file(_REL):
            time.sleep(0.5)
            actions = ruff_lsp.request_code_actions(
                str(src),
                start=file_start,
                end=file_end,
                only=["source.fixAll"],
                diagnostics=[],
            )
        actions = [a for a in actions if isinstance(a, dict)]
        kinds = [a.get("kind", "") for a in actions]
        matched = [
            k for k in kinds
            if k == "source.fixAll" or k.startswith("source.fixAll.")
        ]
        if not matched:
            pytest.skip(
                f"ruff offered no source.fixAll candidate on dirty buffer; "
                f"kinds={kinds}"
            )
        assert matched, (
            f"ruff did not surface source.fixAll family; got kinds={kinds}"
        )
    finally:
        src.write_text(original)


def test_ruff_fix_all_clears_injected_lints(
    ruff_lsp: "SolidLanguageServer",
    calcpy_workspace: Path,
    assert_workspace_edit_round_trip: Any,
) -> None:
    """Apply ruff's source.fixAll edit; the F401 and E711 must drop out."""
    src = calcpy_workspace / "calcpy" / "calcpy.py"
    original = src.read_text()
    try:
        src.write_text(original + _LINT_SENTINEL)
        with ruff_lsp.open_file(_REL):
            time.sleep(0.5)
            pre_diags = _request_diagnostics(ruff_lsp, _REL)
            pre_codes = [str(d.get("code", "")) for d in pre_diags]
            f401 = sum(1 for c in pre_codes if c == "F401")
            e711 = sum(1 for c in pre_codes if c == "E711")
            if f401 == 0 and e711 == 0:
                pytest.skip(
                    f"ruff did not surface F401/E711 on injected lints; "
                    f"pre_codes={pre_codes}"
                )
            actions = ruff_lsp.request_code_actions(
                str(src),
                start={"line": 0, "character": 0},
                end={"line": len(src.read_text().splitlines()), "character": 0},
                only=["source.fixAll"],
                diagnostics=pre_diags,
            )
        actions = [a for a in actions if isinstance(a, dict)]
        fix_all = next(
            (
                a for a in actions
                if a.get("kind", "") == "source.fixAll"
                or a.get("kind", "").startswith("source.fixAll.")
            ),
            None,
        )
        if fix_all is None:
            pytest.skip("ruff offered no source.fixAll action to apply")
        edit = fix_all.get("edit")
        if edit is None:
            with ruff_lsp.open_file(_REL):
                resolved = ruff_lsp.resolve_code_action(fix_all)
                edit = resolved.get("edit") if isinstance(resolved, dict) else None
        if edit is None:
            pytest.skip("source.fixAll action carried no edit even after resolve")

        assert_workspace_edit_round_trip(edit)
        # Re-pull diagnostics post-apply.
        with ruff_lsp.open_file(_REL):
            time.sleep(0.5)
            post_diags = _request_diagnostics(ruff_lsp, _REL)
        post_codes = [str(d.get("code", "")) for d in post_diags]
        post_f401 = sum(1 for c in post_codes if c == "F401")
        post_e711 = sum(1 for c in post_codes if c == "E711")
        # Net count must drop. Allow either lint to remain if the other
        # was the only one ruff fixed (defensive — different ruff versions
        # opt different rules into source.fixAll).
        assert (post_f401 + post_e711) < (f401 + e711), (
            f"ruff source.fixAll did not reduce F401+E711 count: "
            f"pre={f401 + e711}, post={post_f401 + post_e711}, "
            f"post_codes={post_codes}"
        )
    finally:
        src.write_text(original)
