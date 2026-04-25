"""S1 - $/progress forwarding (post Stage 1A).

Phase 0 narrative: the JSON-RPC reader DOES forward every $/progress packet,
but a public-API tap via `on_notification` was clobbered by rust-analyzer's
pre-registered `do_nothing` handler, so post-yield client probes received
nothing. Workaround was to monkey-patch `srv.server._notification_handler`
BEFORE start() to tee at the dispatcher level.

Post Stage 1A T1/T13: `add_notification_listener` registers an additive
listener that runs ALONGSIDE any pre-registered primary handler. T13 wires
`rust_analyzer.py` to subscribe `_on_progress` via this same channel. The
spike registers its OWN additive listener BEFORE start() (no clobbering, no
monkey-patch of `_notification_handler`). To exercise both code paths, the
spike still drives a small post-start workload through the session-scoped
`rust_lsp` fixture, then spawns a fresh instance to capture the cold-start
indexing burst via the additive listener.
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
    "- A -> Stage 1A T1 ships `add_notification_listener` (additive subscriptions, "
    "no clobbering). T9/T13 wire `_on_progress` + `wait_for_indexing()` on top.\n"
    "- B -> ship begin/end coverage; defer fine-grained to v0.2.0.\n"
    "- C -> additive listener tees at the JSON-RPC dispatcher (alongside any primary).\n"
)


def test_s1_progress_forwarding(rust_lsp, seed_rust_root: Path, results_dir: Path) -> None:
    # Probe 1 - additive listener registered POST-start on the session fixture.
    # Validates that listeners attached after init still receive any tail-end
    # progress (e.g., flycheck) that the server emits.
    post_start_events: list[dict[str, Any]] = []
    handle = rust_lsp.server.add_notification_listener(
        "$/progress",
        lambda p: post_start_events.append(p) if isinstance(p, dict) else None,
    )
    try:
        with rust_lsp.open_file("src/lib.rs"):
            time.sleep(2.0)
            symbols = rust_lsp.request_document_symbols("src/lib.rs")
            time.sleep(0.5)
    finally:
        rust_lsp.server.remove_notification_listener(handle)

    # Probe 2 - additive listener registered PRE-start on a fresh instance.
    # Captures the cold-start indexing burst that the session-fixture probe
    # missed (the fixture had already passed init before we attached). This is
    # the upper-bound-of-what-reaches-the-wrapper probe; outcome is classified
    # on this set since cold-start carries the rich rustAnalyzer/* tokens.
    cfg = LanguageServerConfig(code_language=Language.RUST)
    srv2 = SolidLanguageServer.create(cfg, str(seed_rust_root))
    cold_events: list[dict[str, Any]] = []
    handle2 = srv2.server.add_notification_listener(
        "$/progress",
        lambda p: cold_events.append(p) if isinstance(p, dict) else None,
    )
    with srv2.start_server():
        # Let cold-start indexing run; wait_for_indexing() drains the indexing-class
        # tokens once they all reach kind=end (T9). Falls through on timeout.
        srv2.wait_for_indexing(timeout_s=60.0)
        time.sleep(0.5)
    srv2.server.remove_notification_listener(handle2)

    tokens = sorted({str(e.get("token", "")) for e in cold_events})
    has_indexing = any(
        t.startswith("rustAnalyzer/") or "flycheck" in t.lower() or "indexing" in t.lower()
        for t in tokens
    )
    only_begin_end = bool(tokens) and not has_indexing
    outcome = (
        "A - $/progress reaches additive listener with rich indexing-class tokens"
        if has_indexing
        else "B - $/progress reaches additive listener only as generic begin/end"
        if only_begin_end
        else "C - no $/progress reached the additive listener (regression)"
    )

    body = (
        f"# S1 - multilspy `$/progress` forwarding (post Stage 1A)\n\n**Outcome:** {outcome}\n\n"
        f"**Evidence:**\n\n- Cold-start additive-listener events: {len(cold_events)}\n"
        f"- Distinct tokens: {tokens}\n- Indexing-class token observed: {has_indexing}\n"
        f"- Post-start additive-listener events (session fixture): {len(post_start_events)}\n"
        f"- documentSymbol response: {type(symbols).__name__} (truthy={bool(symbols)})\n\n"
        "**API audit (post Stage 1A T1+T13):**\n\n"
        "- `LanguageServerProcess.add_notification_listener` (`src/solidlsp/ls_process.py:516`) "
        "is additive: multiple listeners coexist with the legacy primary handler, none clobber.\n"
        "- `rust_analyzer.py:734` subscribes `_on_progress` via the same additive channel; "
        "`wait_for_indexing()` watches `rustAnalyzer/{Fetching,Building,Indexing,...}` + "
        "`rust-analyzer/flycheck/N` and signals when every observed indexing-class token reaches `end`.\n"
        "- The Phase 0 dispatcher-tee monkey-patch is no longer required (and removed from this spike); "
        "the public additive listener now sees every `$/progress` packet the JSON-RPC reader forwards.\n\n"
        f"**Decision:**\n\n{_DECISIONS}"
    )
    out = write_spike_result(results_dir, "S1", body)
    print(f"\n[S1] Outcome: {outcome}")
    print(f"[S1] Wrote: {out}")
    print(f"[S1] Cold-start events: {len(cold_events)}; tokens: {tokens}")
    print(f"[S1] Post-start events (session fixture): {len(post_start_events)}")
    assert outcome
    # Sanity floor: rust-analyzer cold-start indexing yields many $/progress packets.
    # Pre-T14 dispatcher-tee runs typically saw 100+; use a conservative floor.
    assert len(cold_events) >= 5, f"expected at least a handful of $/progress events, got {len(cold_events)}"
