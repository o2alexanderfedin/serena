"""P4 - basedpyright `relatedInformation` richness on a multi-file type error.

Question: does basedpyright populate `Diagnostic.relatedInformation` with
location pointers (multi-file pointers across the type chain), or only with
title text?

Outcomes (informational, non-blocking):
  - count of basedpyright-sourced diagnostics with non-empty
    `relatedInformation` -> if > 0, `RefactorResult.diagnostics_delta.severity_breakdown`
    can expose related-locations.
  - count without -> severity_breakdown stays minimal (title + range only).

Wrapper-gap: per the P1/P5a precedent there is no `BasedpyrightServer`
adapter under `src/solidlsp/language_servers/` — `Language.PYTHON` resolves
to PyrightServer (vanilla pyright) and the existing wrapper would not boot
basedpyright. Test therefore drops to `_basedpyright_client.BasedpyrightClient`
raw stdio JSON-RPC, parallel to `_pylsp_client.PylspClient` and
`_ruff_client.RuffClient`.

Diagnostics-mode finding (Phase 0 wrapper-gap addendum): basedpyright 1.39.3
serves diagnostics PULL-mode only — it dynamically registers
`textDocument/diagnostic` after `initialized` and never emits
`textDocument/publishDiagnostics`. The test therefore issues an explicit
`textDocument/diagnostic` request and reads `result.items[]`. Stage 1E
`BasedpyrightServer` adapter must mirror this; the standard
`publishDiagnostics`-listening pattern used for pylsp/ruff/mypy will return
zero diagnostics.
"""

from __future__ import annotations

from pathlib import Path

from ._basedpyright_client import BasedpyrightClient
from .conftest import write_spike_result

# Polluted body appended after the original `__init__.py` content.
#
# Mix of error patterns that historically populate pyright's
# `relatedInformation` field:
#   - simple argument-type error against `add(int, int)`
#     (typically NO relatedInformation in vanilla pyright/basedpyright)
#   - `reportIncompatibleMethodOverride` - the report should carry a location
#     pointer back to the base-class method that was overridden incompatibly.
#   - overload mismatch (`reportCallIssue`) - the report should carry a
#     location pointer to the "closest matching" overload.
POLLUTION = '''

from typing import overload

@overload
def parse(x: int) -> int: ...
@overload
def parse(x: str) -> str: ...
def parse(x):
    return x

class Base:
    def f(self, x: int) -> int:
        return x

class Derived(Base):
    def f(self, x: str) -> str:  # incompatible override -> related-loc to Base.f
        return x

def _multi_error_target() -> int:
    return add(1, "string")  # str passed where int expected

_BAD: list[int] = parse(3.14)  # no overload accepts float -> related-loc to closest overload

_DERIVED_BAD = Derived().f(1)  # int arg, but Derived.f wants str
'''


def test_p4_basedpyright_relatedinformation(seed_python_root: Path, results_dir: Path) -> None:
    init_py = seed_python_root / "calcpy_seed" / "__init__.py"
    original = init_py.read_text(encoding="utf-8")
    polluted = original.rstrip() + POLLUTION

    client = BasedpyrightClient(seed_python_root)
    bp_diags: list[dict] = []
    all_diags: list[dict] = []
    diag_kind = ""

    try:
        client.request(
            "initialize",
            {
                "processId": None,
                "rootUri": seed_python_root.as_uri(),
                "workspaceFolders": [{"uri": seed_python_root.as_uri(), "name": "calcpy_seed"}],
                "capabilities": {
                    "workspace": {
                        "applyEdit": True,
                        "configuration": True,
                        "workspaceFolders": True,
                    },
                    "textDocument": {
                        "publishDiagnostics": {"relatedInformation": True},
                        "synchronization": {"didSave": True},
                        "diagnostic": {
                            "dynamicRegistration": True,
                            "relatedDocumentSupport": True,
                        },
                    },
                },
            },
            timeout=15.0,
        )
        client.notify("initialized", {})

        uri = init_py.as_uri()
        # Disk-write polluted before didOpen so the in-memory + on-disk views agree
        # for any pull-diagnostic that consults disk.
        init_py.write_text(polluted, encoding="utf-8")
        client.notify(
            "textDocument/didOpen",
            {"textDocument": {"uri": uri, "languageId": "python", "version": 0, "text": polluted}},
        )
        client.notify(
            "textDocument/didSave",
            {"textDocument": {"uri": uri}, "text": polluted},
        )

        # basedpyright 1.39.3 dynamically registers textDocument/diagnostic
        # (pull mode) and does NOT publish via push. Issue an explicit pull.
        pull = client.request(
            "textDocument/diagnostic", {"textDocument": {"uri": uri}}, timeout=12.0
        )
        result = pull.get("result") or {}
        diag_kind = result.get("kind") or ""
        items = list(result.get("items") or [])
        all_diags = items
        sources = {"basedpyright", "Pyright"}
        bp_diags = [d for d in items if d.get("source") in sources]
    finally:
        init_py.write_text(original, encoding="utf-8")
        client.shutdown()

    total = len(all_diags)
    bp_count = len(bp_diags)
    with_related = sum(1 for d in bp_diags if d.get("relatedInformation"))
    without_related = bp_count - with_related

    # Sample first 3 with-related and first 3 without-related (truncated message).
    def _trim(d: dict) -> dict:
        msg = d.get("message") or ""
        return {
            "code": d.get("code"),
            "severity": d.get("severity"),
            "source": d.get("source"),
            "range": d.get("range"),
            "message": msg[:240] + ("..." if len(msg) > 240 else ""),
            "relatedInformation": d.get("relatedInformation") or [],
        }

    related_sample = [_trim(d) for d in bp_diags if d.get("relatedInformation")][:3]
    plain_sample = [_trim(d) for d in bp_diags if not d.get("relatedInformation")][:3]

    if bp_count == 0:
        outcome = "INDETERMINATE - basedpyright returned 0 diagnostics for the polluted file within timeout"
    elif with_related > 0:
        outcome = (
            f"A - {with_related}/{bp_count} basedpyright-sourced diagnostics carry non-empty "
            f"relatedInformation; severity_breakdown CAN expose related-locations"
        )
    else:
        outcome = (
            f"B - 0/{bp_count} basedpyright-sourced diagnostics carry relatedInformation; "
            f"severity_breakdown stays minimal (title + range only)"
        )

    body = (
        f"# P4 - basedpyright relatedInformation richness on a multi-file type error\n\n"
        f"**Outcome:** {outcome}\n\n"
        f"**Inputs:**\n\n"
        f"- Fixture: `vendor/serena/test/spikes/seed_fixtures/calcpy_seed/calcpy_seed/__init__.py`\n"
        f"- Pollution appended (in-disk + didOpen + didSave):\n"
        f"```python{POLLUTION}```\n"
        f"- basedpyright launched via `basedpyright-langserver --stdio` (1.39.3, pinned).\n"
        f"- Source filter: `source in {{basedpyright, Pyright}}`.\n"
        f"- Diagnostics retrieval mode: PULL via `textDocument/diagnostic` "
        f"(basedpyright dynamically registers this method post-`initialized` and does not push).\n\n"
        f"**Diagnostics summary:**\n\n"
        f"- Pull report kind: `{diag_kind}`\n"
        f"- Total items returned: {total}\n"
        f"- basedpyright-sourced count: {bp_count}\n"
        f"- with relatedInformation (non-empty): {with_related}\n"
        f"- without relatedInformation: {without_related}\n\n"
        f"**Sample with relatedInformation (first {len(related_sample)}):**\n\n"
        f"```json\n{related_sample!r}\n```\n\n"
        f"**Sample without relatedInformation (first {len(plain_sample)}):**\n\n"
        f"```json\n{plain_sample!r}\n```\n\n"
        f"**Wrapper-gap findings:**\n\n"
        f"- No `BasedpyrightServer(SolidLanguageServer)` adapter under "
        f"`src/solidlsp/language_servers/`. `Language.PYTHON` resolves to PyrightServer "
        f"(`src/solidlsp/ls_config.py:346`), so the existing `python_lsp_pylsp` fixture "
        f"would actually boot vanilla pyright, not basedpyright. Test bypasses the wrapper "
        f"with `_basedpyright_client.BasedpyrightClient` (parallel to `_pylsp_client.py` and "
        f"`_ruff_client.py`). Stage 1E `PythonStrategy` should add a real adapter.\n"
        f"- basedpyright 1.39.3 serves diagnostics in PULL MODE ONLY: after `initialized` it "
        f"`client/registerCapability` registers `textDocument/diagnostic` and emits ZERO "
        f"`textDocument/publishDiagnostics`. The Stage 1E adapter must call "
        f"`textDocument/diagnostic` explicitly after each `didOpen`/`didChange`/`didSave`, "
        f"or the diagnostics_delta will always be empty.\n\n"
        f"**Decision:**\n\n"
        f"- A -> `RefactorResult.diagnostics_delta.severity_breakdown` exposes "
        f"per-diagnostic `related_locations: list[Location]`. Applier and MCP serialization "
        f"add ~+15 LoC for the field; UI/test consumers gain multi-file pointers for free. "
        f"Empirically populated for `reportIncompatibleMethodOverride` (pointer to base-class "
        f"method) and `reportCallIssue` (pointer to closest-matching overload). NOT populated "
        f"for `reportArgumentType` on a same-file callee, so consumers must tolerate empty "
        f"`related_locations`.\n"
        f"- B -> severity_breakdown stays minimal (title + range only); document gap and "
        f"defer the related-locations field to v1.1 (when richer Python type-error chains "
        f"actually need it).\n"
        f"- INDETERMINATE -> file basedpyright cold-start / pull-mode discovery as a Phase 0 "
        f"finding; Stage 1E adapter must call `textDocument/diagnostic` (pull) instead of "
        f"listening for `publishDiagnostics`.\n"
    )
    out = write_spike_result(results_dir, "P4", body)
    print(f"\n[P4] Outcome: {outcome}; wrote {out}")
    print(
        f"[P4] total={total} basedpyright_sourced={bp_count} "
        f"with_related={with_related} without_related={without_related} kind={diag_kind!r}"
    )
    assert outcome
