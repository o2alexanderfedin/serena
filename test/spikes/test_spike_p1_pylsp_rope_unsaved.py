"""P1 - pylsp-rope unsaved-buffer behavior.

A: pylsp-rope honors didChange in-memory; resulting WorkspaceEdit text references
the mutated identifier (`plus`). B: pylsp-rope reads from disk; edit references the
on-disk identifier (`add`). Decision: A -> no extra didSave; B -> +~40 LoC + 1 RTT
per call.

Wrapper-gap: SolidLanguageServer's PYTHON adapter is Pyright (ls_config.py:346); no
pylsp adapter exists. Serena's `python_lsp_pylsp` conftest fixture would boot Pyright,
which doesn't load pylsp-rope. Test drops to raw stdio JSON-RPC against `pylsp` (same
pattern S3 used to bypass missing wrapper facades).
"""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Any

from .conftest import write_spike_result


class PylspClient:
    """Minimal stdio JSON-RPC client for pylsp; reads on a background thread."""

    def __init__(self, root: Path) -> None:
        self.proc = subprocess.Popen(
            ["pylsp", "-v"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._id = 0
        self._responses: dict[int, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.apply_edits: list[dict[str, Any]] = []  # captured from workspace/applyEdit reverse-requests
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self.root = root

    def _read_loop(self) -> None:
        assert self.proc.stdout is not None
        stream = self.proc.stdout
        while True:
            length = -1
            while True:  # consume headers until blank line
                line = stream.readline()
                if not line:
                    return
                if line in (b"\r\n", b"\n"):
                    break
                if line.lower().startswith(b"content-length:"):
                    length = int(line.split(b":")[1].strip())
            if length < 0:
                continue
            buf = b""
            while len(buf) < length:
                chunk = stream.read(length - len(buf))
                if not chunk:
                    return
                buf += chunk
            payload = json.loads(buf)
            if "id" in payload and ("result" in payload or "error" in payload):
                with self._lock:
                    self._responses[payload["id"]] = payload
            elif payload.get("method") == "workspace/applyEdit" and "id" in payload:
                # pylsp-rope returns its WorkspaceEdit via this reverse-request, not in executeCommand result.
                self.apply_edits.append(payload.get("params", {}))
                self._send({"jsonrpc": "2.0", "id": payload["id"], "result": {"applied": True}})

    def _send(self, msg: dict[str, Any]) -> None:
        body = json.dumps(msg).encode("utf-8")
        assert self.proc.stdin is not None
        self.proc.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
        self.proc.stdin.flush()

    def request(self, method: str, params: dict[str, Any], timeout: float = 8.0) -> dict[str, Any]:
        self._id += 1
        rid = self._id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        deadline = threading.Event()
        timer = threading.Timer(timeout, deadline.set)
        timer.start()
        try:
            while not deadline.is_set():
                with self._lock:
                    if rid in self._responses:
                        return self._responses.pop(rid)
        finally:
            timer.cancel()
        raise TimeoutError(f"pylsp request {method} timed out after {timeout}s")

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def shutdown(self) -> None:
        try:
            self.request("shutdown", {})
            self.notify("exit", {})
        except Exception:
            pass
        self.proc.terminate()


def test_p1_pylsp_rope_unsaved_buffer(seed_python_root: Path, results_dir: Path) -> None:
    init_py = seed_python_root / "calcpy_seed" / "__init__.py"
    original = init_py.read_text(encoding="utf-8")
    # In-memory rename `add` -> `plus` plus a call site we can inline against.
    mutated = original.replace("def add(", "def plus(").replace('"add"', '"plus"') + "\n_TEST_CALL = plus(1, 2)\n"
    plus_def_line = mutated.splitlines().index("def plus(a: int, b: int) -> int:")  # 0-indexed line of `def plus`

    client = PylspClient(seed_python_root)
    try:
        init = client.request(
            "initialize",
            {
                "processId": None,
                "rootUri": seed_python_root.as_uri(),
                "capabilities": {"workspace": {"applyEdit": True, "workspaceEdit": {"documentChanges": True}}},
            },
            timeout=15.0,
        )
        client.notify("initialized", {})
        plugins_loaded = init.get("result", {}).get("capabilities", {}).get("executeCommandProvider", {}).get("commands", [])
        rope_loaded = any(c.startswith("pylsp_rope.") for c in plugins_loaded)

        uri = init_py.as_uri()
        client.notify("textDocument/didOpen", {"textDocument": {"uri": uri, "languageId": "python", "version": 0, "text": original}})
        client.notify(
            "textDocument/didChange",
            {"textDocument": {"uri": uri, "version": 1}, "contentChanges": [{"text": mutated}]},  # full-document sync
        )

        # Probe: code-action surface at `def plus(` token; pylsp-rope returns generic titles + commands.
        ca_resp = client.request(
            "textDocument/codeAction",
            {
                "textDocument": {"uri": uri},
                "range": {"start": {"line": plus_def_line, "character": 4}, "end": {"line": plus_def_line, "character": 8}},
                "context": {"diagnostics": []},
            },
        )
        actions = [a for a in ca_resp.get("result", []) if isinstance(a, dict)]
        rope_actions = [
            a for a in actions if isinstance(a.get("command"), dict) and a["command"].get("command", "").startswith("pylsp_rope.")
        ]
        # pylsp-rope returns command-typed actions (refactoring.py:73-81); no codeAction/resolve needed
        # (resolve materializes for deferred-resolution servers like rust-analyzer per S3 finding).

        # Direct pylsp-rope signal: execute Inline at `def plus` -> WorkspaceEdit arrives via
        # `workspace/applyEdit` reverse-request (project.py:158 calls `workspace.apply_edit(...)`),
        # NOT in the executeCommand result. Inspect captured edits.
        # If pylsp-rope reads in-memory (project.py:181-191 -> `document.source`), edit references `plus`.
        # If it reads disk, the call site `_TEST_CALL = plus(1, 2)` doesn't exist there; result is empty or `add`-typed.
        edit_err: str | None = None
        try:
            ec_resp = client.request(
                "workspace/executeCommand",
                {
                    "command": "pylsp_rope.refactor.inline",
                    "arguments": [{"document_uri": uri, "position": {"line": plus_def_line, "character": 4}}],
                },
                timeout=12.0,
            )
            edit_err = (ec_resp.get("error") or {}).get("message")
        except Exception as exc:
            edit_err = repr(exc)
        edit_text = ""
        for params in client.apply_edits:
            we = params.get("edit") or {}
            for _u, edits in (we.get("changes") or {}).items():
                for e in edits or []:
                    edit_text += e.get("newText", "")
            for change in we.get("documentChanges") or []:
                for e in change.get("edits") or []:
                    edit_text += e.get("newText", "")
    finally:
        client.shutdown()

    # The mutated-only call site `_TEST_CALL = plus(1, 2)` exists ONLY in-memory; the on-disk
    # __init__.py has no call sites for any function. So a non-empty Inline edit proves pylsp-rope
    # saw the in-memory buffer. The inlined newText `_TEST_CALL = 1 + 2` (body substituted at call)
    # is the positive signal; an empty edit or `add`-typed edit would mean disk-read.
    inlined_call_site = "_TEST_CALL = 1 + 2" in edit_text  # exact body-substitution result for `plus(1, 2)`
    sees_add = "add" in edit_text and "plus" not in edit_text
    if not rope_loaded:
        outcome = "INDETERMINATE - pylsp-rope plugin not registered (executeCommandProvider lacks pylsp_rope.* commands)"
    elif inlined_call_site:
        outcome = "A - pylsp-rope honors didChange in-memory; no extra didSave needed"
    elif sees_add:
        outcome = "B - pylsp-rope reads from disk; scalpel must didSave({includeText: true}) before every code-action call"
    elif client.apply_edits:
        outcome = f"INDETERMINATE - applyEdit fired but inlined text unrecognized: {edit_text!r}"
    else:
        outcome = f"INDETERMINATE - inline produced no edit (err={edit_err!r})"

    body = (
        f"# P1 - pylsp-rope unsaved-buffer behavior\n\n"
        f"**Outcome:** {outcome}\n\n**Evidence:**\n\n"
        f"- pylsp-rope plugin loaded (executeCommandProvider has `pylsp_rope.*`): {rope_loaded}\n"
        f"- Code actions surfaced at `def plus(` position: {len(actions)} (pylsp-rope-typed: {len(rope_actions)})\n"
        f"- Inline executeCommand error: {edit_err!r}\n"
        f"- workspace/applyEdit reverse-requests captured: {len(client.apply_edits)}\n"
        f"- Inline WorkspaceEdit newText (concatenated): {edit_text!r}\n"
        f"- Inlined call site `_TEST_CALL = 1 + 2` present (in-memory-only signal): {inlined_call_site}; "
        f"'add' (no 'plus') present: {sees_add}\n\n"
        "**API audit (2026-04-24):**\n\n"
        "- Wrapper gap: `SolidLanguageServer` PYTHON adapter is Pyright (ls_config.py:346), NOT pylsp. "
        "No pylsp adapter exists in `src/solidlsp/language_servers/`. Test bypasses wrapper via raw stdio JSON-RPC.\n"
        "- pylsp-rope code actions are command-typed (refactoring.py:72-81) with generic titles "
        "(`Extract method`, `Inline method/variable/parameter`); identifier-classification requires inspecting "
        "executeCommand WorkspaceEdit text, not action titles (plan §4 illustrative classifier won't work as written).\n"
        "- pylsp-rope reads via `workspace.get_maybe_document(uri).source` (project.py:181-191), "
        "i.e., the in-memory pylsp document buffer; transitively, didChange honoring depends on pylsp updating that buffer.\n\n"
        "**Decision:**\n\n"
        "- A -> Stage 1E pythonStrategy passes the buffer via `didChange` only.\n"
        "- B -> Stage 1E pythonStrategy injects `didSave({includeText: true})` before every code-action call (+~40 LoC, +1 RTT per call).\n"
        "- INDETERMINATE -> file pylsp-rope plugin-loading or inline-handler issue as Phase 0 finding; re-run with broader inline target or different command.\n"
    )
    out = write_spike_result(results_dir, "P1", body)
    print(f"\n[P1] Outcome: {outcome}; wrote {out}")
    print(
        f"[P1] rope_loaded={rope_loaded} actions={len(actions)} rope_actions={len(rope_actions)} edit_len={len(edit_text)} err={edit_err!r}"
    )
    assert outcome
