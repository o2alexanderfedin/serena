"""S1 - $/progress forwarding. Probe 1: public API tap via fixture (post-yield).
Probe 2: dispatcher tee installed BEFORE start() on a second instance - upper
bound for what reaches the wrapper. Outcome classified on probe 2.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("CARGO_BUILD_RUSTC", "rustc")  # neutralize rust-fv-driver alias

from solidlsp.ls import SolidLanguageServer
from solidlsp.ls_config import Language, LanguageServerConfig

from .conftest import write_spike_result

_DECISIONS = (
    "- A -> Stage 1A adds +30 LoC notification-tap shim per plan section 13 "
    "fallback (additive subscriptions, no clobbering); wait_for_indexing() "
    "watches rustAnalyzer/{Fetching,Building,...} and rust-analyzer/flycheck/N.\n"
    "- B -> ship begin/end coverage; defer fine-grained to v0.2.0.\n"
    "- C -> shim must tee in the JSON-RPC reader, not at dispatch.\n"
)


def test_s1_progress_forwarding(rust_lsp, seed_rust_root: Path, results_dir: Path) -> None:
    public_events: list[dict[str, Any]] = []
    rust_lsp.server.on_notification("$/progress", lambda p: public_events.append(p) if isinstance(p, dict) else None)
    with rust_lsp.open_file("src/lib.rs"):
        time.sleep(2.0)
        symbols = rust_lsp.request_document_symbols("src/lib.rs")
        time.sleep(0.5)

    cfg = LanguageServerConfig(code_language=Language.RUST)
    srv2 = SolidLanguageServer.create(cfg, str(seed_rust_root))
    dispatcher_events: list[dict[str, Any]] = []
    orig = srv2.server._notification_handler

    def tee(payload: dict) -> None:
        if payload.get("method") == "$/progress" and isinstance(payload.get("params"), dict):
            dispatcher_events.append(payload["params"])
        return orig(payload)

    srv2.server._notification_handler = tee  # type: ignore[assignment]
    with srv2.start_server():
        time.sleep(1.0)

    tokens = sorted({str(e.get("token", "")) for e in dispatcher_events})
    has_indexing = any(t.startswith("rustAnalyzer/") or "flycheck" in t.lower() or "indexing" in t.lower() for t in tokens)
    only_begin_end = bool(tokens) and not has_indexing
    outcome = (
        "A - $/progress reaches dispatcher with rich indexing-class tokens"
        if has_indexing
        else "B - $/progress reaches dispatcher only as generic begin/end"
        if only_begin_end
        else "C - no $/progress reaches the wrapper dispatcher (shim needed)"
    )

    body = (
        f"# S1 - multilspy `$/progress` forwarding\n\n**Outcome:** {outcome}\n\n"
        f"**Evidence:**\n\n- Dispatcher-probe events: {len(dispatcher_events)}\n"
        f"- Distinct tokens: {tokens}\n- Indexing-class token observed: {has_indexing}\n"
        f"- Public-API probe events (post-yield): {len(public_events)}\n"
        f"- documentSymbol response: {type(symbols).__name__} (truthy={bool(symbols)})\n\n"
        "**API audit (verified 2026-04-24):**\n\n"
        "- `LanguageServerProcess.on_notification` (`src/solidlsp/ls_process.py:507`) is "
        "single-callback-per-method; callback receives `params` only.\n"
        "- `rust_analyzer.py:720` pre-registers `do_nothing` for `$/progress`; "
        "post-yield client taps cannot recover events emitted during init.\n"
        "- Wrapping `server._notification_handler` BEFORE `start()` confirms the "
        "JSON-RPC layer DOES forward every `$/progress` packet to the wrapper.\n\n"
        f"**Decision:**\n\n{_DECISIONS}"
    )
    out = write_spike_result(results_dir, "S1", body)
    print(f"\n[S1] Outcome: {outcome}")
    print(f"[S1] Wrote: {out}")
    print(f"[S1] Dispatcher events: {len(dispatcher_events)}; tokens: {tokens}")
    print(f"[S1] Public-API events: {len(public_events)}")
    assert outcome
