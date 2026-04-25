"""Minimal stdio JSON-RPC client for `basedpyright-langserver` — used by Phase 0
spikes that need basedpyright's diagnostic surface (P4 relatedInformation
richness; P3a green-bar baseline).

Wrapper-gap context: SolidLanguageServer's PYTHON adapter resolves to the stock
PyrightServer (see `src/solidlsp/ls_config.py:346`), NOT basedpyright. There is
no `BasedpyrightServer(SolidLanguageServer)` adapter under
`src/solidlsp/language_servers/`. Spikes that probe basedpyright-specific
behavior (its richer diagnostic format vs. vanilla pyright; its stricter rule
set; ...) must therefore drop to raw stdio JSON-RPC. This client is the
canonical implementation, parallel to `_pylsp_client.PylspClient` and
`_ruff_client.RuffClient`.

Stage 1E `PythonStrategy` will replace this with a real adapter (template:
`jedi_server.py`, ~50 LoC).

Captures `textDocument/publishDiagnostics` notifications into
`self.diagnostics_by_uri[uri]` (last-write-wins) so spikes that need to
observe diagnostic deltas (P4 relatedInformation count; P3a baseline) can
read them. Also captures `workspace/applyEdit` reverse-requests for parity
with `PylspClient` even though basedpyright does not currently send them on
the spike fixtures.
"""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Any


class BasedpyrightClient:
    """Minimal stdio JSON-RPC client for basedpyright-langserver."""

    def __init__(self, root: Path) -> None:
        self.proc = subprocess.Popen(
            ["basedpyright-langserver", "--stdio"],
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
            method = payload.get("method")
            if "id" in payload and ("result" in payload or "error" in payload):
                # Response to a client->server request.
                with self._lock:
                    self._responses[payload["id"]] = payload
            elif method == "workspace/applyEdit" and "id" in payload:
                self.apply_edits.append(payload.get("params", {}))
                self._send({"jsonrpc": "2.0", "id": payload["id"], "result": {"applied": True}})
            elif method == "textDocument/publishDiagnostics":
                params = payload.get("params") or {}
                uri = params.get("uri")
                if uri:
                    with self._lock:
                        self.diagnostics_by_uri[uri] = list(params.get("diagnostics") or [])
            elif method and "id" in payload:
                # Other server -> client requests (e.g. workspace/configuration,
                # client/registerCapability, window/workDoneProgress/create).
                # basedpyright BLOCKS on these — must respond or pull-diagnostics
                # never returns.
                if method == "workspace/configuration":
                    items = (payload.get("params") or {}).get("items") or []
                    self._send({
                        "jsonrpc": "2.0",
                        "id": payload["id"],
                        "result": [{} for _ in items],
                    })
                else:
                    # registerCapability / workDoneProgress/create / etc — ack with null.
                    self._send({"jsonrpc": "2.0", "id": payload["id"], "result": None})

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
        raise TimeoutError(f"basedpyright request {method} timed out after {timeout}s")

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def shutdown(self) -> None:
        try:
            self.request("shutdown", {})
            self.notify("exit", {})
        except Exception:
            pass
        self.proc.terminate()
