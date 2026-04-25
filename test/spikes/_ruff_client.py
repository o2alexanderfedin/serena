"""Minimal stdio JSON-RPC client for `ruff server` — used by Phase 0 spikes that need
ruff's source-action surface (organize-imports, fixAll).

Wrapper-gap context: SolidLanguageServer has no Ruff adapter (mirrors the pylsp gap
documented in `_pylsp_client.py`). Stage 1E `PythonStrategy` will add a real adapter;
until then, P2 / P5a / P-WB drop to raw stdio JSON-RPC.

Mirrors `PylspClient`'s `request` / `notify` / `shutdown` API and `apply_edits` capture.
ruff returns `WorkspaceEdit` payloads inline in code-action `edit:` fields rather than
via `workspace/applyEdit` reverse-requests, but we still capture reverse-requests for
parity (ruff CAN send them when an action is executed via `workspace/executeCommand`,
e.g. `ruff.applyOrganizeImports`).
"""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Any


class RuffClient:
    """Minimal stdio JSON-RPC client for `ruff server`; reads on a background thread."""

    def __init__(self, root: Path) -> None:
        self.proc = subprocess.Popen(
            ["ruff", "server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._id = 0
        self._responses: dict[int, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.apply_edits: list[dict[str, Any]] = []
        self.diagnostics: list[dict[str, Any]] = []
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
                self.diagnostics.append(payload.get("params", {}))

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
        raise TimeoutError(f"ruff request {method} timed out after {timeout}s")

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def shutdown(self) -> None:
        try:
            self.request("shutdown", {})
            self.notify("exit", {})
        except Exception:
            pass
        self.proc.terminate()
