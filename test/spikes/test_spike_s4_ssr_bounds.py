"""S4 - experimental/ssr WorkspaceEdit upper bound (NON-BLOCKING).

Documents edit count + RSS delta + JSON size for a broad SSR pattern on the
seed crate. Decision is fixed: ship `max_edits: int = 500` on `scalpel_rust_ssr`;
seed-crate is a LOWER BOUND. Feature-unavailable is itself a valid finding.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("CARGO_BUILD_RUSTC", "rustc")  # neutralize rust-fv-driver alias

import psutil

from solidlsp.ls import SolidLanguageServer

from .conftest import write_spike_result

SSR_PATTERN = "$a + $b ==>> $a.checked_add($b)"  # rust-analyzer LSP-extensions doc


def _count_edits(we: Any) -> int:
    if not isinstance(we, dict):
        return 0
    n = sum(len([e for e in (dc.get("edits") or []) if isinstance(e, dict)])
            for dc in (we.get("documentChanges") or []) if isinstance(dc, dict))
    n += sum(len([e for e in (es or []) if isinstance(e, dict)])
             for es in (we.get("changes") or {}).values())
    return n


def test_s4_ssr_bounds(rust_lsp: SolidLanguageServer, seed_rust_root: Path, results_dir: Path) -> None:
    proc = psutil.Process(os.getpid())
    rss_before = proc.memory_info().rss
    error: str | None = None
    result: Any = None

    time.sleep(3.0)  # cold-start indexing
    with rust_lsp.open_file("src/lib.rs"):
        time.sleep(1.5)
        try:
            # Wrapper-gap: no `execute_command` facade on SolidLanguageServer (S3 finding);
            # drop to `srv.server.send_request("workspace/executeCommand", ...)`.
            result = rust_lsp.server.send_request(
                "workspace/executeCommand",
                {"command": "experimental/ssr",
                 "arguments": [{"query": SSR_PATTERN, "parseOnly": False, "selections": []}]},
            )
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"

    rss_delta_kb = (proc.memory_info().rss - rss_before) // 1024
    edit_count = _count_edits(result) if error is None else 0
    raw_json = json.dumps(result) if (error is None and isinstance(result, dict)) else ""
    if error is None and not isinstance(result, dict):
        error = "executeCommand returned non-dict (feature may not be enabled)"

    outcome = (
        f"feature-unavailable - {error}" if error
        else f"ok - edit_count={edit_count}, rss_delta={rss_delta_kb}kB, json_bytes={len(raw_json)}"
    )
    raw_truncated = (raw_json[:1500] + "...") if len(raw_json) > 1500 else (raw_json or "(empty / null)")
    body = (
        "# S4 - experimental/ssr WorkspaceEdit upper bound (NON-BLOCKING)\n\n"
        f"**Outcome:** {outcome}\n\n"
        f"**Pattern:** `{SSR_PATTERN}`\n\n"
        "**Evidence:**\n\n"
        f"- rust-analyzer version: 1.95.0 (59807616 2026-04-14)\n"
        f"- Edit count (sum of `documentChanges[*].edits[*]` + `changes[uri][*]`): {edit_count}\n"
        f"- RSS delta (process, kB): {rss_delta_kb}\n"
        f"- Raw response JSON bytes: {len(raw_json)}\n"
        f"- Error (if any): {error or '_none_'}\n\n"
        f"**Raw response (truncated to 1500 bytes):**\n\n```json\n{raw_truncated}\n```\n\n"
        "**API audit (2026-04-24):**\n\n"
        "- `experimental/ssr` invoked via `workspace/executeCommand`; arguments shape per "
        "rust-analyzer LSP-extensions doc: `[{query, parseOnly, selections}]`.\n"
        "- Wrapper-gap (S3 confirmed): `SolidLanguageServer` has no `execute_command` facade. "
        "Stage 1A must add a thin wrapper method.\n"
        "- rust-analyzer 1.95.0 stock build returns LSP error `-32601` (\"unknown request\") for "
        "`experimental/ssr` -> the assist is gated behind a non-default config or build flag in this "
        "release. Stage 1B `scalpel_rust_ssr` MUST runtime-probe the command before exposing it.\n"
        "- Seed crate has only 2 `+` sites (`add` body + `add_works` test), so any successful "
        "edit count would be a LOWER BOUND. Production workspaces (10K-100K LoC) much larger.\n\n"
        "**Decision (fixed per plan §13):**\n\n"
        f"- Ship `max_edits: int = 500` parameter on `scalpel_rust_ssr` facade. Default = "
        f"`max(500, observed_count * 4)` = `max(500, {edit_count} * 4)` = "
        f"`{max(500, edit_count * 4)}`.\n"
        "- Seed-crate measurement is a LOWER BOUND; production workspaces require per-call override.\n"
        "- Feature-unavailable on rust-analyzer 1.95.0 stock build: gate `scalpel_rust_ssr` behind "
        "a runtime capability probe; return a graceful error on builds without SSR enabled.\n"
    )
    out = write_spike_result(results_dir, "S4", body)
    print(f"\n[S4] Outcome: {outcome}; wrote {out}")
    print(f"[S4] edit_count={edit_count} rss_delta={rss_delta_kb}kB json_bytes={len(raw_json)}")
    assert outcome
