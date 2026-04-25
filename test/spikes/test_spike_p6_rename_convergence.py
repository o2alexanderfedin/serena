"""P6 - pylsp vs basedpyright `textDocument/rename` convergence (NON-BLOCKING).

Question: when pylsp and basedpyright both serve a `rename` request on the same
symbol, do their `WorkspaceEdit`s converge to the same set of edits?

Outcome (informational): capture both LSPs' rename edit sets, normalize to
`(uri, line, char_start, line, char_end, newText)` tuples, compute symmetric
difference. The decision (per scope-report §11.1) is fixed: if divergence > 0,
the multi-server merger picks pylsp for `textDocument/rename` and logs a
`provenance.disagreement` warning. This spike documents the divergence shape so
the merger has data to write against.

Wrapper-gap context (per P1/P4/P5a): `Language.PYTHON` resolves to PyrightServer
(`src/solidlsp/ls_config.py:346`); neither pylsp nor basedpyright has a
`SolidLanguageServer` adapter. Test reuses the raw stdio JSON-RPC clients
extracted to `_pylsp_client.PylspClient` and `_basedpyright_client.BasedpyrightClient`
(parallel to `_ruff_client.py`). Stage 1E `PythonStrategy` will replace both
with real adapters (~50 LoC each).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._basedpyright_client import BasedpyrightClient
from ._pylsp_client import PylspClient
from .conftest import write_spike_result

EditTuple = tuple[str, int, int, int, int, str]


def _normalize(edit: dict[str, Any] | None) -> set[EditTuple]:
    """Normalize a `WorkspaceEdit` (either `documentChanges` or legacy `changes`
    shape) to a set of (uri, sl, sc, el, ec, newText) tuples for set comparison.
    """
    out: set[EditTuple] = set()
    if not isinstance(edit, dict):
        return out
    for tde in edit.get("documentChanges") or []:
        if not isinstance(tde, dict):
            continue
        uri = ((tde.get("textDocument") or {}).get("uri")) or ""
        for te in tde.get("edits") or []:
            r = te.get("range") or {}
            s = r.get("start") or {}
            e = r.get("end") or {}
            out.add(
                (
                    uri,
                    int(s.get("line", -1)),
                    int(s.get("character", -1)),
                    int(e.get("line", -1)),
                    int(e.get("character", -1)),
                    te.get("newText", ""),
                )
            )
    for uri, edits in (edit.get("changes") or {}).items():
        for te in edits or []:
            r = te.get("range") or {}
            s = r.get("start") or {}
            e = r.get("end") or {}
            out.add(
                (
                    uri,
                    int(s.get("line", -1)),
                    int(s.get("character", -1)),
                    int(e.get("line", -1)),
                    int(e.get("character", -1)),
                    te.get("newText", ""),
                )
            )
    return out


def _initialize(client: Any, root: Path) -> None:
    client.request(
        "initialize",
        {
            "processId": None,
            "rootUri": root.as_uri(),
            "workspaceFolders": [{"uri": root.as_uri(), "name": root.name}],
            "capabilities": {
                "workspace": {
                    "applyEdit": True,
                    "configuration": True,
                    "workspaceFolders": True,
                    "workspaceEdit": {"documentChanges": True},
                },
                "textDocument": {
                    "synchronization": {"didSave": True},
                    "rename": {"prepareSupport": False},
                    "diagnostic": {"dynamicRegistration": True},
                },
            },
        },
        timeout=15.0,
    )
    client.notify("initialized", {})


def _rename(client: Any, uri: str, line: int, character: int) -> tuple[dict[str, Any] | None, str]:
    try:
        resp = client.request(
            "textDocument/rename",
            {"textDocument": {"uri": uri}, "position": {"line": line, "character": character}, "newName": "plus"},
            timeout=12.0,
        )
    except Exception as exc:  # raw client may TimeoutError or similar
        return None, f"request-exception: {type(exc).__name__}: {exc}"
    if "error" in resp:
        return None, f"lsp-error: {resp.get('error')!r}"
    return (resp.get("result") if isinstance(resp.get("result"), dict) else None), ""


def test_p6_rename_convergence(seed_python_root: Path, results_dir: Path) -> None:
    init_py = seed_python_root / "calcpy_seed" / "__init__.py"
    text = init_py.read_text(encoding="utf-8")
    lines = text.splitlines()
    # Locate `def add(` to compute (line, character) of the function name token.
    def_line = next(i for i, ln in enumerate(lines) if ln.startswith("def add("))
    name_col = lines[def_line].index("add")
    uri = init_py.as_uri()

    pylsp = PylspClient(seed_python_root)
    bp = BasedpyrightClient(seed_python_root)
    pylsp_edit: dict[str, Any] | None = None
    bp_edit: dict[str, Any] | None = None
    pylsp_err = ""
    bp_err = ""

    try:
        _initialize(pylsp, seed_python_root)
        _initialize(bp, seed_python_root)

        pylsp.notify(
            "textDocument/didOpen",
            {"textDocument": {"uri": uri, "languageId": "python", "version": 0, "text": text}},
        )
        bp.notify(
            "textDocument/didOpen",
            {"textDocument": {"uri": uri, "languageId": "python", "version": 0, "text": text}},
        )

        pylsp_edit, pylsp_err = _rename(pylsp, uri, def_line, name_col)
        bp_edit, bp_err = _rename(bp, uri, def_line, name_col)
    finally:
        pylsp.shutdown()
        bp.shutdown()

    pylsp_set = _normalize(pylsp_edit)
    bp_set = _normalize(bp_edit)
    only_pylsp = pylsp_set - bp_set
    only_bp = bp_set - pylsp_set
    sym_diff = len(only_pylsp) + len(only_bp)

    if not pylsp_set and not bp_set:
        outcome = (
            f"INDETERMINATE - both LSPs returned 0 rename edits "
            f"(pylsp_err={pylsp_err!r}, bp_err={bp_err!r})"
        )
    elif sym_diff == 0:
        outcome = (
            f"CONVERGENT - both LSPs returned identical edit sets of size "
            f"{len(pylsp_set)}; multi-server merger sees 0 disagreement on this symbol"
        )
    else:
        outcome = (
            f"DIVERGENT - pylsp={len(pylsp_set)} bp={len(bp_set)} "
            f"only_in_pylsp={len(only_pylsp)} only_in_basedpyright={len(only_bp)}; "
            f"merger picks pylsp per scope-report §11.1 and logs provenance.disagreement"
        )

    sample_pylsp = sorted(pylsp_set)[:5]
    sample_bp = sorted(bp_set)[:5]
    sample_only_pylsp = sorted(only_pylsp)[:5]
    sample_only_bp = sorted(only_bp)[:5]

    body = (
        f"# P6 - pylsp vs basedpyright textDocument/rename convergence\n\n"
        f"**Outcome:** {outcome}\n\n"
        f"**Symbol:**\n\n"
        f"- File: `vendor/serena/test/spikes/seed_fixtures/calcpy_seed/calcpy_seed/__init__.py`\n"
        f"- Token: `add` (function name on `def add(a: int, b: int) -> int:`)\n"
        f"- Position: line={def_line} (0-indexed), character={name_col}\n"
        f"- New name: `plus`\n\n"
        f"**Per-LSP edit set sizes:**\n\n"
        f"- pylsp: {len(pylsp_set)} edit tuple(s); request-error: {pylsp_err!r}\n"
        f"- basedpyright: {len(bp_set)} edit tuple(s); request-error: {bp_err!r}\n\n"
        f"**Symmetric difference:**\n\n"
        f"- only_in_pylsp: {len(only_pylsp)}\n"
        f"- only_in_basedpyright: {len(only_bp)}\n"
        f"- total symmetric difference: {sym_diff}\n\n"
        f"**Sample edits (first 5, sorted; tuple = uri, sl, sc, el, ec, newText):**\n\n"
        f"- pylsp:\n```python\n{sample_pylsp!r}\n```\n"
        f"- basedpyright:\n```python\n{sample_bp!r}\n```\n"
        f"- only_in_pylsp:\n```python\n{sample_only_pylsp!r}\n```\n"
        f"- only_in_basedpyright:\n```python\n{sample_only_bp!r}\n```\n\n"
        f"**Wrapper-gap findings (re-confirmed from P1/P4/P5a):**\n\n"
        f"- `Language.PYTHON` resolves to PyrightServer (`src/solidlsp/ls_config.py:346`); "
        f"neither pylsp nor basedpyright has a `SolidLanguageServer` adapter. Test bypasses "
        f"the wrapper via `_pylsp_client.PylspClient` + `_basedpyright_client.BasedpyrightClient`. "
        f"Stage 1E `PythonStrategy` must add real adapters (~50 LoC each, template `jedi_server.py`).\n"
        f"- basedpyright requires the server->client request auto-responder for "
        f"`workspace/configuration` / `client/registerCapability` / `window/workDoneProgress/create`; "
        f"`BasedpyrightClient` already handles all three so `textDocument/rename` returns normally.\n\n"
        f"**Decision (per scope-report §11.1, fixed):**\n\n"
        f"- CONVERGENT -> multi-server merger sees 0 disagreement on this symbol; no "
        f"`provenance.disagreement` warning fires; either LSP's edit set is canonical.\n"
        f"- DIVERGENT -> merger picks pylsp for `textDocument/rename` and logs a "
        f"`provenance.disagreement` warning carrying the symmetric-difference summary "
        f"(only_in_pylsp / only_in_basedpyright counts + first-N samples). The MVP `RefactorResult` "
        f"surface should expose this delta so callers can audit the merge.\n"
        f"- INDETERMINATE -> file as a Phase 0 finding; Stage 1D merger must tolerate one or both "
        f"LSPs returning empty/null rename results (e.g. unsupported file types, server boot failures).\n"
    )
    out = write_spike_result(results_dir, "P6", body)
    print(f"\n[P6] Outcome: {outcome}; wrote {out}")
    print(
        f"[P6] pylsp_edits={len(pylsp_set)} bp_edits={len(bp_set)} "
        f"only_pylsp={len(only_pylsp)} only_bp={len(only_bp)}"
    )
    assert outcome
