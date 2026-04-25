"""S3 - workspace/applyEdit reverse-request on command-typed code actions.
A: applyEdit fires -> Stage 1A full handler (+80 LoC). B: no fire -> minimal stub (~+20 LoC).
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
    "- A -> Stage 1A implements full applyEdit handler in "
    "solidlsp/lsp_protocol_handler/server.py (+80 LoC) delegating to WorkspaceEditApplier.\n"
    "- B -> Stage 1A ships minimal `{applied: true, failureReason: null}` stub (~+20 LoC); "
    "reclaim ~50 LoC. Re-verify in S4/S5/S6 with richer fixtures (ssr, expandMacro, auto_import).\n"
)


def test_s3_apply_edit_reverse_request(seed_rust_root: Path, results_dir: Path) -> None:
    cfg = LanguageServerConfig(code_language=Language.RUST)
    srv = SolidLanguageServer.create(cfg, str(seed_rust_root))
    apply_edit_calls: list[dict[str, Any]] = []

    # Public on_request keeps rust-analyzer from stalling; dispatcher-tee is the
    # canonical S1 pattern (single-callback-per-method dispatcher at ls_process.py:534).
    srv.server.on_request("workspace/applyEdit", lambda p: {"applied": True, "failureReason": None})
    orig_req = srv.server._request_handler

    def tee(payload: dict[str, Any]) -> None:
        if payload.get("method") == "workspace/applyEdit" and isinstance(payload.get("params"), dict):
            apply_edit_calls.append(payload["params"])
        return orig_req(payload)

    srv.server._request_handler = tee  # type: ignore[assignment]

    actions: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []
    command_actions: list[dict[str, Any]] = []
    edit_actions: list[dict[str, Any]] = []
    executed = 0

    with srv.start_server():
        time.sleep(3.0)  # cold-start indexing
        with srv.open_file("src/lib.rs"):
            time.sleep(1.5)
            uri = (seed_rust_root / "src" / "lib.rs").as_uri()
            # Two ranges so we surface both refactor.inline (add name) and refactor.extract (whole fn).
            for rng in (
                {"start": {"line": 0, "character": 7}, "end": {"line": 0, "character": 10}},
                {"start": {"line": 0, "character": 0}, "end": {"line": 2, "character": 1}},
            ):
                params = {"textDocument": {"uri": uri}, "range": rng, "context": {"diagnostics": []}}
                raw = srv.server.send_request("textDocument/codeAction", params) or []
                actions.extend(a for a in raw if isinstance(a, dict))

            # rust-analyzer returns deferred-resolution actions (data only); resolve to materialize
            # command/edit fields. This is canonical client behavior.
            for a in actions:
                try:
                    r = srv.server.send_request("codeAction/resolve", a)
                    if isinstance(r, dict):
                        resolved.append(r)
                except Exception:
                    resolved.append(a)
            command_actions = [a for a in resolved if a.get("command") and not a.get("edit")]
            edit_actions = [a for a in resolved if a.get("edit")]

            for action in command_actions[:3]:
                cmd = action["command"] if isinstance(action.get("command"), dict) else {}
                try:
                    srv.server.send_request(
                        "workspace/executeCommand",
                        {"command": cmd.get("command", ""), "arguments": cmd.get("arguments", [])},
                    )
                except Exception:
                    pass
                executed += 1
                time.sleep(0.5)

    if apply_edit_calls:
        outcome = "A - applyEdit reverse-request fired; full handler required"
    elif command_actions:
        outcome = "B - command-typed actions exist but applyEdit did not fire (edit embedded in executeCommand response)"
    elif edit_actions:
        outcome = f"B - all {len(edit_actions)} resolved actions carry `edit:` directly; no command-typed action surfaced (minimal stub sufficient, re-verify S4/S5/S6)"
    else:
        outcome = "B - no actions surfaced on fixture; minimal stub sufficient (re-verify S4/S5/S6)"

    body = (
        f"# S3 - workspace/applyEdit reverse-request on command-typed code actions\n\n"
        f"**Outcome:** {outcome}\n\n**Evidence:**\n\n"
        f"- Code actions surfaced (lib.rs add-name + whole-fn ranges): {len(actions)}\n"
        f"- Resolved actions (after `codeAction/resolve`): {len(resolved)}\n"
        f"- `command:`-typed actions (command set, edit empty): {len(command_actions)}\n"
        f"- `edit:`-typed actions: {len(edit_actions)}\n"
        f"- executeCommand attempts: {executed}\n"
        f"- `workspace/applyEdit` reverse-requests observed: {len(apply_edit_calls)}\n\n"
        "**API audit (2026-04-24):**\n\n"
        "- rust-analyzer returns deferred-resolution actions: top-level response carries only "
        "`{title, kind, data, group?}`; `command`/`edit` populate only after `codeAction/resolve`. "
        "Stage 1A code-action flow MUST resolve before classifying.\n"
        "- `SolidLanguageServer` has NO `request_code_actions` / `resolve_code_action` / "
        "`execute_command` facade; test uses `srv.server.send_request(...)` directly. "
        "Stage 1A: add facade methods (wrapper-gap finding).\n"
        "- `on_request` (`ls_process.py:501`) is single-callback-per-method (S1 constraint). "
        "`rust_analyzer.py:706-723` does NOT pre-register `workspace/applyEdit`; public registration "
        "survives unclobbered, dispatcher-tee added belt-and-suspenders.\n\n"
        f"**Decision:**\n\n{_DECISIONS}"
    )
    out = write_spike_result(results_dir, "S3", body)
    print(f"\n[S3] Outcome: {outcome}; wrote {out}")
    print(
        f"[S3] raw={len(actions)} resolved={len(resolved)} cmd={len(command_actions)} edit={len(edit_actions)} exec={executed} applyEdit={len(apply_edit_calls)}"
    )
    assert outcome
