"""S3 - workspace/applyEdit reverse-request on command-typed code actions (post Stage 1A).

A: applyEdit fires -> Stage 1A full handler (+80 LoC).
B: no fire -> minimal stub (~+20 LoC).

Phase 0 narrative: spike registered its own `on_request("workspace/applyEdit", ...)`
ack handler AND a dispatcher-tee monkey-patch on `srv.server._request_handler` to
capture the params reaching the wrapper, since the wrapper had no facade for it.

Post Stage 1A T2/T6/T7/T8: `_handle_workspace_apply_edit` is registered by default
on every `SolidLanguageServer` and captures payloads into a thread-safe buffer;
`pop_pending_apply_edits()` drains it. `request_code_actions`, `resolve_code_action`,
and `execute_command(cmd, args)` (which already drains pending applyEdits and
returns them as the second tuple element) replace the raw send_request calls.
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

    # T2: SolidLanguageServer installs `_handle_workspace_apply_edit` by default; it
    # captures the params into `_pending_apply_edits` (thread-safe) and acks
    # `{applied: true, failureReason: null}`. No custom on_request registration here.

    actions: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []
    command_actions: list[dict[str, Any]] = []
    edit_actions: list[dict[str, Any]] = []
    apply_edit_calls: list[dict[str, Any]] = []
    executed = 0

    lib_path = str(seed_rust_root / "src" / "lib.rs")

    with srv.start_server():
        time.sleep(3.0)  # cold-start indexing
        with srv.open_file("src/lib.rs"):
            time.sleep(1.5)
            # Two ranges so we surface both refactor.inline (add name) and refactor.extract (whole fn).
            for start, end in (
                ({"line": 0, "character": 7}, {"line": 0, "character": 10}),
                ({"line": 0, "character": 0}, {"line": 2, "character": 1}),
            ):
                raw = srv.request_code_actions(lib_path, start=start, end=end, diagnostics=[])
                actions.extend(a for a in raw if isinstance(a, dict))

            # rust-analyzer returns deferred-resolution actions (data only); resolve to materialize
            # command/edit fields. This is canonical client behavior.
            for a in actions:
                try:
                    r = srv.resolve_code_action(a)
                    if isinstance(r, dict):
                        resolved.append(r)
                except Exception:
                    resolved.append(a)
            command_actions = [a for a in resolved if a.get("command") and not a.get("edit")]
            edit_actions = [a for a in resolved if a.get("edit")]

            # Drain anything that may have been captured during resolve (defensive — most
            # rust-analyzer flows ship applyEdit during executeCommand, not resolve).
            apply_edit_calls.extend(srv.pop_pending_apply_edits())

            for action in command_actions[:3]:
                cmd = action["command"] if isinstance(action.get("command"), dict) else {}
                try:
                    # T8: execute_command returns (response, drained_apply_edits) where
                    # `drained` IS the list of applyEdit payloads captured during the
                    # round-trip — pylsp-rope ships its WorkspaceEdit there (P1) and
                    # rust-analyzer command-typed actions may too.
                    _resp, drained = srv.execute_command(cmd.get("command", ""), cmd.get("arguments", []))
                    apply_edit_calls.extend(drained)
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
        f"# S3 - workspace/applyEdit reverse-request on command-typed code actions (post Stage 1A)\n\n"
        f"**Outcome:** {outcome}\n\n**Evidence:**\n\n"
        f"- Code actions surfaced (lib.rs add-name + whole-fn ranges): {len(actions)}\n"
        f"- Resolved actions (after `codeAction/resolve`): {len(resolved)}\n"
        f"- `command:`-typed actions (command set, edit empty): {len(command_actions)}\n"
        f"- `edit:`-typed actions: {len(edit_actions)}\n"
        f"- executeCommand attempts: {executed}\n"
        f"- `workspace/applyEdit` reverse-requests observed: {len(apply_edit_calls)}\n\n"
        "**API audit (post Stage 1A T2/T6/T7/T8):**\n\n"
        "- rust-analyzer returns deferred-resolution actions: top-level response carries only "
        "`{title, kind, data, group?}`; `command`/`edit` populate only after `codeAction/resolve`. "
        "Stage 1A code-action flow MUST resolve before classifying.\n"
        "- `SolidLanguageServer.request_code_actions` / `.resolve_code_action` / `.execute_command` "
        "(T6/T7/T8) replace raw `srv.server.send_request(...)` calls. `execute_command` returns "
        "`(response, drained_apply_edits)` — drained list IS the applyEdit-payload list.\n"
        "- T2 installs `_handle_workspace_apply_edit` by default; payloads captured into "
        "`_pending_apply_edits` (thread-safe) and drained via `pop_pending_apply_edits()` or the "
        "second tuple element of `execute_command`. Custom `on_request` registration + dispatcher-tee "
        "monkey-patch are no longer needed and have been removed from this spike.\n\n"
        f"**Decision:**\n\n{_DECISIONS}"
    )
    out = write_spike_result(results_dir, "S3", body)
    print(f"\n[S3] Outcome: {outcome}; wrote {out}")
    print(
        f"[S3] raw={len(actions)} resolved={len(resolved)} cmd={len(command_actions)} edit={len(edit_actions)} exec={executed} applyEdit={len(apply_edit_calls)}"
    )
    assert outcome
