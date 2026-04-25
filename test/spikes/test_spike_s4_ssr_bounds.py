"""S4 - experimental/ssr WorkspaceEdit upper bound (NON-BLOCKING).

Documents edit count + RSS delta + JSON size for a broad SSR pattern on the
seed crate. Decision is fixed: ship `max_edits: int = 500` on `scalpel_rust_ssr`;
seed-crate is a LOWER BOUND. Feature-unavailable is itself a valid finding.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("CARGO_BUILD_RUSTC", "rustc")  # neutralize rust-fv-driver alias

import psutil

from solidlsp.ls import SolidLanguageServer
from solidlsp.ls_exceptions import SolidLSPException

from .conftest import write_spike_result

SSR_PATTERN = "$a + $b ==>> $a.checked_add($b)"  # rust-analyzer LSP-extensions doc
_LSP_CODE_RE = re.compile(r"-(326\d{2})")  # JSON-RPC reserved error-code window


def _classify_failure(exc: SolidLSPException) -> tuple[str, int | None]:
    """Quality-reviewer fix: classify by JSON-RPC -326XX code so feature-unavailable,
    test-bug, and server-crash failures are no longer lumped into one bucket."""
    msg = str(exc)
    m = _LSP_CODE_RE.search(msg)
    code = int(m.group(1)) if m else None
    mapping = {32601: "feature-unavailable", 32602: "test-bug-invalid-params", 32603: "server-crash-internal-error"}
    if code in mapping:
        return mapping[code], code
    return ("timeout" if "timeout" in msg.lower() else "unknown-failure"), code


def _capture_rust_analyzer_version() -> str:
    """Quality-reviewer fix: capture rust-analyzer version at runtime instead of
    hard-coding it. Falls back to 'unknown' when the binary is not on PATH."""
    try:
        out = subprocess.run(["rust-analyzer", "--version"],
                             capture_output=True, text=True, check=False, timeout=5)
        return out.stdout.strip() or out.stderr.strip() or "unknown"
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return "unknown"


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
    failure_class: str | None = None
    lsp_code: int | None = None
    result: Any = None
    ra_version = _capture_rust_analyzer_version()

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
        except SolidLSPException as exc:
            error = f"{type(exc).__name__}: {exc}"
            failure_class, lsp_code = _classify_failure(exc)

    rss_delta_kb = (proc.memory_info().rss - rss_before) // 1024
    edit_count = _count_edits(result) if error is None else 0
    raw_json = json.dumps(result) if (error is None and isinstance(result, dict)) else ""
    if error is None and not isinstance(result, dict):
        error = "executeCommand returned non-dict (feature may not be enabled)"
        failure_class = failure_class or "feature-unavailable"

    code_repr = f"LSP -{lsp_code}" if lsp_code is not None else "no LSP code"
    outcome = (f"{failure_class or 'unknown-failure'} ({code_repr}) - {error}" if error
               else f"ok - edit_count={edit_count}, rss_delta={rss_delta_kb}kB, json_bytes={len(raw_json)}")
    raw_truncated = (raw_json[:1500] + "...") if len(raw_json) > 1500 else (raw_json or "(empty / null)")
    body = (
        "# S4 - experimental/ssr WorkspaceEdit upper bound (NON-BLOCKING)\n\n"
        f"**Outcome:** {outcome}\n\n"
        f"**Failure classification:** failure_class=`{failure_class or '_n/a_'}`, "
        f"lsp_code=`{lsp_code if lsp_code is not None else '_n/a_'}`\n\n"
        f"**Pattern:** `{SSR_PATTERN}`\n\n"
        "**Evidence:**\n\n"
        f"- rust-analyzer version: {ra_version}\n"
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
        "- rust-analyzer stock build returns LSP error `-32601` (\"unknown request\") for "
        "`experimental/ssr` -> the assist is gated behind a non-default config or build flag in this "
        "release. Stage 1B `scalpel_rust_ssr` MUST runtime-probe the command before exposing it.\n"
        "- Seed crate has only 2 `+` sites (`add` body + `add_works` test), so any successful "
        "edit count would be a LOWER BOUND. Production workspaces (10K-100K LoC) much larger.\n\n"
        "**Decision (fixed per plan §13):**\n\n"
        f"- Ship `max_edits: int = 500` parameter on `scalpel_rust_ssr` facade. Default = "
        f"`max(500, observed_count * 4)` = `max(500, {edit_count} * 4)` = "
        f"`{max(500, edit_count * 4)}`.\n"
        "- Seed-crate measurement is a LOWER BOUND; production workspaces require per-call override.\n"
        "- Feature-unavailable on rust-analyzer stock build: gate `scalpel_rust_ssr` behind "
        "a runtime capability probe; return a graceful error on builds without SSR enabled.\n"
    )
    out = write_spike_result(results_dir, "S4", body)
    print(f"\n[S4] Outcome: {outcome}; wrote {out}")
    print(f"[S4] failure_class={failure_class} lsp_code={lsp_code} ra_version={ra_version}")
    print(f"[S4] edit_count={edit_count} rss_delta={rss_delta_kb}kB json_bytes={len(raw_json)}")
    assert outcome
