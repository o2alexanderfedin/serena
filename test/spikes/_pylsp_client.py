"""Minimal stdio JSON-RPC client for `pylsp` — used by Phase 0 spikes that need
the pylsp + pylsp-rope toolchain.

Wrapper-gap context: SolidLanguageServer's PYTHON adapter resolves to PyrightServer
(see `src/solidlsp/ls_config.py:346`). No `PylspServer` adapter exists in
`src/solidlsp/language_servers/`. Spikes that probe pylsp/pylsp-rope/pylsp-mypy/
pylsp-ruff behavior must therefore drop to raw stdio JSON-RPC. This client is the
canonical implementation, originally embedded inline in `test_spike_p1_pylsp_rope_unsaved.py`
and extracted here for re-use across P2 / P5a / P3 / P4 / P6.

Stage 1E `PythonStrategy` will replace this with a real `PylspServer(SolidLanguageServer)`
adapter (template: `jedi_server.py`, ~50 LoC).
"""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Any


class PylspClient:
    """Minimal stdio JSON-RPC client for pylsp; reads on a background thread.

    Captures `workspace/applyEdit` reverse-requests because pylsp-rope returns
    its `WorkspaceEdit` payload via that channel, not via the `executeCommand`
    response. Each captured payload is appended to `self.apply_edits`.

    Captures `textDocument/publishDiagnostics` notifications into
    `self.diagnostics_by_uri[uri]` (last-write-wins) so spikes that need to
    observe diagnostic deltas (e.g., P5a pylsp-mypy stale-rate) can read them.
    """

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
        self.apply_edits: list[dict[str, Any]] = []
        self.diagnostics_by_uri: dict[str, list[dict[str, Any]]] = {}
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self.root = root

    def _read_loop(self) -> None:
        assert self.proc.stdout is not None
        stream = self.proc.stdout
        while True:
            length = -1
            while True:
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
                self.apply_edits.append(payload.get("params", {}))
                self._send({"jsonrpc": "2.0", "id": payload["id"], "result": {"applied": True}})
            elif payload.get("method") == "textDocument/publishDiagnostics":
                params = payload.get("params") or {}
                uri = params.get("uri")
                if uri:
                    with self._lock:
                        self.diagnostics_by_uri[uri] = list(params.get("diagnostics") or [])

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
