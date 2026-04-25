"""S5 - rust-analyzer/expandMacro on macro_rules vs proc-macro positions (NON-BLOCKING).

Outcomes:
  A: expansion succeeds at BOTH macro_rules! and #[derive(...)] positions.
  B: declarative-only.
  feature-unavailable: server returns LSP -32601 for both positions.
  INDETERMINATE: mixed / position-not-found / unknown failure mode.
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

from solidlsp.ls import SolidLanguageServer
from solidlsp.ls_exceptions import SolidLSPException

from .conftest import write_spike_result

_LSP_CODE_RE = re.compile(r"-(326\d{2})")  # JSON-RPC reserved error-code window


def _classify_failure(exc: SolidLSPException) -> tuple[str, int | None]:
    """Reused from S4: classify by JSON-RPC -326XX code."""
    msg = str(exc)
    m = _LSP_CODE_RE.search(msg)
    code = int(m.group(1)) if m else None
    mapping = {32601: "feature-unavailable", 32602: "test-bug-invalid-params", 32603: "server-crash-internal-error"}
    if code in mapping:
        return mapping[code], code
    return ("timeout" if "timeout" in msg.lower() else "unknown-failure"), code


def _capture_rust_analyzer_version() -> str:
    """Reused from S4: capture rust-analyzer --version at runtime; never hard-code."""
    try:
        out = subprocess.run(["rust-analyzer", "--version"], capture_output=True, text=True, check=False, timeout=5)
        return out.stdout.strip() or out.stderr.strip() or "unknown"
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return "unknown"


def _find_position(lines: list[str], needle: str) -> tuple[int, int] | None:
    for i, line in enumerate(lines):
        c = line.find(needle)
        if c >= 0:
            return (i, c)
    return None


def _expand_at(srv: SolidLanguageServer, uri: str, line: int, character: int) -> dict[str, Any]:
    """Return {result, err, failure_class, lsp_code}. Catches SolidLSPException only."""
    try:
        r = srv.server.send_request(
            "workspace/executeCommand",
            {"command": "rust-analyzer/expandMacro",
             "arguments": [{"textDocument": {"uri": uri}, "position": {"line": line, "character": character}}]},
        )
        return {"result": r, "err": None, "failure_class": None, "lsp_code": None}
    except SolidLSPException as exc:
        fc, code = _classify_failure(exc)
        return {"result": None, "err": f"{type(exc).__name__}: {exc}", "failure_class": fc, "lsp_code": code}


def _ok(r: Any) -> bool:
    return isinstance(r, dict) and isinstance(r.get("expansion"), str) and bool(r["expansion"])


def _summarize(rec: dict[str, Any]) -> str:
    if rec["err"] is not None:
        return f"err={rec['err']}; failure_class={rec['failure_class']}; lsp_code={rec['lsp_code']}"
    r = rec["result"]
    if isinstance(r, dict) and "expansion" in r:
        exp = r.get("expansion") or ""
        return f"ok; expansion_bytes={len(exp)}; name={r.get('name')!r}; preview={exp[:200]!r}"
    return f"unexpected_result_shape; raw={json.dumps(r)[:200] if r is not None else 'None'}"


def test_s5_expand_macro(rust_lsp: SolidLanguageServer, seed_rust_root: Path, results_dir: Path) -> None:
    ra_version = _capture_rust_analyzer_version()
    lib_rs = seed_rust_root / "src" / "lib.rs"
    uri = lib_rs.as_uri()
    lines = lib_rs.read_text().splitlines()
    decl_pos = _find_position(lines, "decl_macro!(zero)")
    derive_pos = _find_position(lines, "#[derive(Debug, Clone)]")

    time.sleep(3.0)  # cold-start indexing
    decl: dict[str, Any] = {"result": None, "err": "position-not-found", "failure_class": None, "lsp_code": None}
    derive: dict[str, Any] = {"result": None, "err": "position-not-found", "failure_class": None, "lsp_code": None}
    with rust_lsp.open_file("src/lib.rs"):
        time.sleep(1.5)
        if decl_pos is not None:
            decl = _expand_at(rust_lsp, uri, decl_pos[0], decl_pos[1])
        if derive_pos is not None:
            derive = _expand_at(rust_lsp, uri, derive_pos[0], derive_pos[1])

    decl_ok = _ok(decl["result"]) and decl["err"] is None
    derive_ok = _ok(derive["result"]) and derive["err"] is None
    both_32601 = decl["lsp_code"] == 32601 and derive["lsp_code"] == 32601

    if decl_ok and derive_ok:
        outcome = "A - expansion succeeds at BOTH macro_rules and #[derive(...)] positions"
        decision = "scalpel_rust_expand_macro exposes both declarative and proc-macro positions"
    elif decl_ok and not derive_ok:
        outcome = "B - expansion declarative-only (macro_rules ok; #[derive] not expanded)"
        decision = "facade returns not_supported_for_proc_macros on derive/attribute positions"
    elif both_32601:
        outcome = "feature-unavailable (LSP -32601) - rust-analyzer/expandMacro not registered"
        decision = "facade unavailable until rust-analyzer is built with expandMacro support"
    else:
        outcome = (f"INDETERMINATE - decl_ok={decl_ok} ({_summarize(decl)}); "
                   f"derive_ok={derive_ok} ({_summarize(derive)}); "
                   f"decl_pos={decl_pos}, derive_pos={derive_pos}")
        decision = "verify positions and rust-analyzer version; re-run before classifying"

    def _raw(rec: dict[str, Any]) -> str:
        r = rec["result"]
        return json.dumps(r)[:600] if isinstance(r, dict) else repr(r)

    body = (
        "# S5 - rust-analyzer/expandMacro on macro_rules vs proc-macro (NON-BLOCKING)\n\n"
        f"**Outcome:** {outcome}\n\n"
        "**Evidence:**\n\n"
        f"- rust-analyzer version: {ra_version}\n"
        f"- Fixture: `{lib_rs}` (proc-macro target gated by `#[cfg(feature = \"_spike_proc_macro\")]`)\n"
        f"- decl_macro position (line, char): {decl_pos}\n"
        f"- derive position (line, char): {derive_pos}\n"
        f"- decl_macro result: {_summarize(decl)}\n"
        f"- derive result: {_summarize(derive)}\n\n"
        "**Per-position raw response (truncated to 600 bytes):**\n\n"
        f"- decl: `{_raw(decl)}`\n"
        f"- derive: `{_raw(derive)}`\n\n"
        "**API audit (2026-04-24):**\n\n"
        "- `rust-analyzer/expandMacro` invoked via `workspace/executeCommand` with arguments shape "
        "`[{textDocument: {uri}, position: {line, character}}]` per rust-analyzer LSP-extensions doc.\n"
        "- Wrapper-gap (S3/S4 confirmed): `SolidLanguageServer` has no `execute_command` facade; "
        "test drops to `srv.server.send_request(...)`.\n"
        "- Failure classification reuses S4's `_classify_failure(exc) -> (failure_class, lsp_code)` "
        "pattern (32601 -> feature-unavailable, 32602 -> test-bug, 32603 -> server-crash).\n\n"
        f"**Decision:**\n\n- {decision}\n"
    )
    out = write_spike_result(results_dir, "S5", body)
    print(f"\n[S5] Outcome: {outcome}; wrote {out}")
    print(f"[S5] decl: {_summarize(decl)}")
    print(f"[S5] derive: {_summarize(derive)}")
    print(f"[S5] ra_version={ra_version}")
    assert outcome
