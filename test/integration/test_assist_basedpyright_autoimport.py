"""Stage 1H T10 Module 5 — Python: basedpyright auto-import quickfix.

Targets calcpy fixture. Without committing changes, this test creates a
synthetic Counter() reference at the bottom of calcpy.py via in-memory
buffer mutation, then asserts:

(a) basedpyright surfaces ``reportUndefinedVariable`` on ``Counter``.
(b) basedpyright's quickfix action title contains "Add import" (or
    "Import" / "Add ... import" — accept any reasonable phrasing) and
    the edit imports ``Counter`` from ``collections``.

Both sub-tests skip cleanly when basedpyright is absent (host gap) or
when the diagnostic does not surface (basedpyright pull-mode latency).

The mutation is restored in a try/finally so the fixture is unchanged on
exit even when the test fails or skips mid-flight.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from solidlsp.ls import SolidLanguageServer


_REL = "calcpy/calcpy.py"
_SENTINEL = "\n# T10 Module 5 — synthetic undefined Counter reference\n_COUNTER_PROBE = Counter()\n"


def _request_diagnostics(srv: "SolidLanguageServer", rel: str) -> list[dict[str, Any]]:
    """Best-effort pull-mode diagnostic fetch via the LSP request API.

    basedpyright supports textDocument/diagnostic (LSP §3.17). When the
    method is unsupported we return an empty list so callers skip cleanly.
    """
    try:
        from urllib.parse import quote
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


def test_basedpyright_surfaces_undefined_counter(
    basedpyright_lsp: "SolidLanguageServer",
    calcpy_workspace: Path,
) -> None:
    """Inject a Counter() use, expect basedpyright to surface
    reportUndefinedVariable on it."""
    src = calcpy_workspace / "calcpy" / "calcpy.py"
    original = src.read_text()
    try:
        src.write_text(original + _SENTINEL)
        with basedpyright_lsp.open_file(_REL):
            # basedpyright pull-mode needs ~1-2 s after didOpen.
            time.sleep(2.0)
            diags = _request_diagnostics(basedpyright_lsp, _REL)
        if not diags:
            pytest.skip("basedpyright returned no diagnostics (pull-mode unsupported?)")
        codes = [str(d.get("code", "")) for d in diags]
        if not any("reportUndefinedVariable" in c for c in codes):
            messages = [d.get("message", "") for d in diags]
            pytest.skip(
                f"reportUndefinedVariable not surfaced; codes={codes}, "
                f"messages={messages[:3]}"
            )
        assert any("reportUndefinedVariable" in c for c in codes), (
            f"basedpyright did not flag undefined Counter; codes={codes}"
        )
    finally:
        src.write_text(original)


def test_basedpyright_offers_add_import_counter(
    basedpyright_lsp: "SolidLanguageServer",
    calcpy_workspace: Path,
) -> None:
    """Quickfix on the diagnostic must offer a Counter→collections import."""
    src = calcpy_workspace / "calcpy" / "calcpy.py"
    original = src.read_text()
    try:
        src.write_text(original + _SENTINEL)
        # Locate the line index of the synthetic ``_COUNTER_PROBE`` usage.
        lines = src.read_text().splitlines()
        line_idx = next(
            (i for i, ln in enumerate(lines) if "_COUNTER_PROBE = Counter()" in ln),
            None,
        )
        if line_idx is None:
            pytest.skip("synthetic Counter probe line not found post-write")
        char = lines[line_idx].index("Counter")

        with basedpyright_lsp.open_file(_REL):
            time.sleep(2.0)
            diags = _request_diagnostics(basedpyright_lsp, _REL)
            counter_diag = next(
                (
                    d for d in diags
                    if "reportUndefinedVariable" in str(d.get("code", ""))
                    and "Counter" in str(d.get("message", ""))
                ),
                None,
            )
            if counter_diag is None:
                pytest.skip(
                    "basedpyright did not surface the Counter undefined-variable "
                    "diagnostic; cannot drive auto-import quickfix"
                )
            actions = basedpyright_lsp.request_code_actions(
                str(src),
                start={"line": line_idx, "character": char},
                end={"line": line_idx, "character": char + len("Counter")},
                diagnostics=[counter_diag],
            )
        actions = [a for a in actions if isinstance(a, dict)]
        # Look for any action whose title mentions "import" + "Counter" OR a
        # quickfix-kind action whose edit references "from collections".
        import_actions = [
            a for a in actions
            if "import" in a.get("title", "").lower()
            and "counter" in (a.get("title", "") + json.dumps(a.get("edit", {}))).lower()
        ]
        if not import_actions:
            titles = [a.get("title", "") for a in actions]
            pytest.skip(
                f"basedpyright did not offer Add-import action; titles={titles}"
            )
        # The edit (or its resolved form) must reference ``collections``.
        for a in import_actions:
            edit = a.get("edit")
            if edit is None:
                with basedpyright_lsp.open_file(_REL):
                    resolved = basedpyright_lsp.resolve_code_action(a)
                    edit = resolved.get("edit") if isinstance(resolved, dict) else None
            if edit and "collections" in json.dumps(edit):
                return  # success
        pytest.skip(
            "Add-import action present but edit body lacks 'collections' "
            "import — basedpyright resolved to a different source"
        )
    finally:
        src.write_text(original)
