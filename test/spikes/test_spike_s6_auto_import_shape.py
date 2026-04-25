"""S6 - auto_import resolve shape (edit: vs command:) on rust-analyzer (post Stage 1A, NON-BLOCKING).

A: every auto_import action carries `edit:` after resolve -> applier branches on edit only.
B: some are command-only -> applier handles both shapes (+40 LoC two-shape branch).

Phase 0 narrative: spike used raw `srv.server.send_request("textDocument/codeAction", ...)`
and `"codeAction/resolve"` because no facade existed. Post Stage 1A T6/T7, the public
`request_code_actions` / `resolve_code_action` facades replace the raw calls.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("CARGO_BUILD_RUSTC", "rustc")  # neutralize rust-fv-driver alias

from solidlsp.ls import SolidLanguageServer  # noqa: E402

from .conftest import write_spike_result  # noqa: E402

# Pollutant references HashMap without an import; rust-analyzer should surface
# an "Import HashMap" quickfix on the HashMap token.
_POLLUTANT = "\npub fn uses_hashmap(m: HashMap<i64, i64>) -> usize { m.len() }\n"


def _classify(a: dict[str, Any]) -> str:
    e, c = bool(a.get("edit")), bool(a.get("command"))
    return "both" if e and c else "edit_only" if e else "command_only" if c else "neither"


def _is_auto_import(a: dict[str, Any]) -> bool:
    title = (a.get("title") or "").lower()
    kind = a.get("kind") or ""
    return "import" in title or (isinstance(kind, str) and kind.startswith("quickfix.import"))


def test_s6_auto_import_shape(rust_lsp: SolidLanguageServer, seed_rust_root: Path, results_dir: Path) -> None:
    srv = rust_lsp
    time.sleep(3.0)  # cold-start indexing
    actions: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []

    lib_path = str(seed_rust_root / "src" / "lib.rs")

    with srv.open_file("src/lib.rs") as fb:
        time.sleep(1.5)
        original_text = fb.contents
        polluted = original_text + _POLLUTANT
        # Send polluted buffer via didChange ONLY — no disk write, no didSave.
        # rust-analyzer advertises Incremental sync (kind=2); a single contentChange
        # without `range` is the LSP §3.18.6 "replace whole document" form and is honored.
        fb.version += 1
        fb.contents = polluted
        srv.server.notify.did_change_text_document(
            {
                "textDocument": {"uri": fb.uri, "version": fb.version},
                "contentChanges": [{"text": polluted}],
            }
        )
        time.sleep(2.5)  # let RA re-analyze

        # Find HashMap token in the appended region; offset -> (line, character).
        hm_offset = polluted.index("HashMap", len(original_text))
        hm_line = polluted.count("\n", 0, hm_offset)
        hm_char = hm_offset - (polluted.rfind("\n", 0, hm_offset) + 1)
        start = {"line": hm_line, "character": hm_char}
        end = {"line": hm_line, "character": hm_char + len("HashMap")}
        # No `only` filter — auto-imports surface variously under quickfix / quickfix.import.*;
        # post-filter on title/kind. T6 facade replaces raw send_request.
        raw = srv.request_code_actions(lib_path, start=start, end=end, diagnostics=[])
        actions.extend(a for a in raw if isinstance(a, dict))

        # S3 finding: rust-analyzer returns deferred-resolution actions; resolve BEFORE classify.
        # T7 facade replaces raw send_request("codeAction/resolve", ...).
        for a in actions:
            try:
                r = srv.resolve_code_action(a)
                resolved.append(r if isinstance(r, dict) else a)
            except Exception:
                resolved.append(a)

    auto_imports = [a for a in resolved if _is_auto_import(a)]
    counts = {"edit_only": 0, "command_only": 0, "both": 0, "neither": 0}
    for a in auto_imports:
        counts[_classify(a)] += 1

    if not auto_imports:
        outcome = "INDETERMINATE - no auto_import actions surfaced (indexing not ready or pollutant not recognized)"
    elif counts["command_only"] == 0 and counts["neither"] == 0:
        outcome = (
            f"A - all {len(auto_imports)} auto_import actions carry `edit:` after resolve "
            f"(edit_only={counts['edit_only']}, both={counts['both']}); applier branches on edit only"
        )
    else:
        outcome = (
            f"B - {counts['command_only']} command-only and {counts['neither']} neither out of "
            f"{len(auto_imports)} auto_import actions; applier needs two-shape branch (+40 LoC)"
        )

    titles_blob = "\n".join(
        f"- `{a.get('title')}` (kind={a.get('kind')!r}, shape={_classify(a)})" for a in auto_imports[:10]
    ) or "_(none)_"
    body = (
        f"# S6 - auto_import resolve shape (edit: vs command:) (post Stage 1A)\n\n"
        f"**Outcome:** {outcome}\n\n**Evidence:**\n\n"
        f"- Code actions surfaced (HashMap range on polluted didChange buffer): {len(actions)}\n"
        f"- Resolved actions (after `codeAction/resolve`): {len(resolved)}\n"
        f"- auto_import-filtered actions (title 'import' or kind startswith `quickfix.import`): {len(auto_imports)}\n"
        f"- Shape tally: edit_only={counts['edit_only']}, command_only={counts['command_only']}, "
        f"both={counts['both']}, neither={counts['neither']}\n"
        f"- HashMap token range: line={hm_line}, char={hm_char}..{hm_char + len('HashMap')}\n\n"
        f"**Auto_import actions (up to 10):**\n\n{titles_blob}\n\n"
        "**API audit (post Stage 1A T6/T7):**\n\n"
        "- Polluted buffer delivered via `textDocument/didChange` only (full-doc content change); "
        "no disk write, no didSave. fb.version bumped + fb.contents synced for client-side parity.\n"
        "- S3 finding applied: every action goes through `codeAction/resolve` BEFORE classification.\n"
        "- `SolidLanguageServer.request_code_actions` / `.resolve_code_action` (T6/T7) replace the "
        "raw `srv.server.send_request(...)` calls used in Phase 0.\n\n"
        "**Decision:**\n\n"
        "- A -> applier branches on `edit:` only (+0 LoC vs. optimistic).\n"
        "- B -> applier handles both shapes (+40 LoC: edit -> WorkspaceEditApplier; "
        "command -> executeCommand + applyEdit-stub WorkspaceEdit capture).\n"
        "- INDETERMINATE -> re-run with longer indexing budget or richer pollutant; assume B for safety.\n"
    )
    out = write_spike_result(results_dir, "S6", body)
    print(f"\n[S6] Outcome: {outcome}; wrote {out}")
    print(f"[S6] raw={len(actions)} resolved={len(resolved)} auto_import={len(auto_imports)} shape={counts}")
    assert outcome
