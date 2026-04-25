"""P5a - pylsp-mypy stale-rate falsifier (per Q1 resolution).

Configures pylsp-mypy with `live_mode: false` + `dmypy: true` and injects a
`textDocument/didSave({includeText: true})` after each mutation, then compares
the mypy-sourced `publishDiagnostics` count against a ground-truth `dmypy run`
oracle on the same on-disk file across 12 internal apply-equivalent steps.

Outcomes per Q1 resolution:
  A: stale_rate < 5% AND p95 < 1s -> ship pylsp-mypy in MVP active set.
  B: stale_rate < 5% AND p95 1-3s -> ship with documented warning.
  C: stale_rate >= 5% OR p95 >= 3s OR cache corruption -> drop pylsp-mypy
     from MVP active set; basedpyright sole type-error source per MVP §11.1.

Wrapper-gap: per P1 finding, no PylspServer adapter exists; test uses raw
stdio JSON-RPC via `_pylsp_client.PylspClient` (extended with publishDiagnostics
capture for this spike).
"""

from __future__ import annotations

import statistics
import subprocess
import time
from pathlib import Path

from ._pylsp_client import PylspClient
from .conftest import write_spike_result

EDITS = [
    'BAD_VAR_1: int = "string"',
    'BAD_VAR_2: list[int] = [1, 2, "x"]',
    "BAD_VAR_3: int = None",
    "BAD_VAR_4: dict[str, int] = {1: 1}",
    "BAD_VAR_5: tuple[int, int] = (1, 2, 3)",
    'BAD_VAR_6: set[int] = {"a", "b"}',
    "BAD_VAR_7: int = []",
    "BAD_VAR_8: list[str] = [1, 2]",
    "BAD_VAR_9: bool = 'true'",
    "BAD_VAR_10: float = 'pi'",
    'BAD_VAR_11: int = "still wrong"',
    'BAD_VAR_12: list[int] = "not a list"',
]


def _wait_for_mypy_diagnostics(client: PylspClient, uri: str, timeout: float = 8.0) -> tuple[float, list[dict]]:
    """Poll diagnostics_by_uri every 50ms; return (elapsed, mypy-sourced list)."""
    deadline = time.perf_counter() + timeout
    start = time.perf_counter()
    while time.perf_counter() < deadline:
        diags = client.diagnostics_by_uri.get(uri, [])
        mypy_diags = [d for d in diags if d.get("source") == "mypy"]
        if mypy_diags:
            return time.perf_counter() - start, mypy_diags
        time.sleep(0.05)
    return time.perf_counter() - start, [d for d in client.diagnostics_by_uri.get(uri, []) if d.get("source") == "mypy"]


def test_p5a_pylsp_mypy_didsave_stale_rate(seed_python_root: Path, results_dir: Path) -> None:
    init_py = seed_python_root / "calcpy_seed" / "__init__.py"
    original = init_py.read_text(encoding="utf-8")
    base = original.rstrip() + "\n"

    client = PylspClient(seed_python_root)
    latencies: list[float] = []
    pairs: list[tuple[int, int]] = []
    plugin_loaded = False
    dmypy_errors: list[str] = []

    try:
        client.request(
            "initialize",
            {
                "processId": None,
                "rootUri": seed_python_root.as_uri(),
                "capabilities": {
                    "workspace": {"applyEdit": True, "configuration": True},
                    "textDocument": {"publishDiagnostics": {"relatedInformation": True}, "synchronization": {"didSave": True}},
                },
                "initializationOptions": {"pylsp": {"plugins": {"pylsp_mypy": {"enabled": True, "live_mode": False, "dmypy": True}}}},
            },
            timeout=15.0,
        )
        client.notify("initialized", {})
        client.notify(
            "workspace/didChangeConfiguration",
            {"settings": {"pylsp": {"plugins": {"pylsp_mypy": {"enabled": True, "live_mode": False, "dmypy": True}}}}},
        )

        uri = init_py.as_uri()
        client.notify(
            "textDocument/didOpen",
            {"textDocument": {"uri": uri, "languageId": "python", "version": 0, "text": base}},
        )

        # Probe: confirm pylsp-mypy plugin actually loaded by waiting for the first
        # `mypy`-sourced publishDiagnostics on a known-bad first edit.
        for version, replacement in enumerate(EDITS, start=1):
            mutated = base + replacement + "\n"
            init_py.write_text(mutated, encoding="utf-8")
            client.notify(
                "textDocument/didChange",
                {"textDocument": {"uri": uri, "version": version}, "contentChanges": [{"text": mutated}]},
            )
            # Clear last diagnostic snapshot so we wait for THIS step's publish.
            client.diagnostics_by_uri.pop(uri, None)
            client.notify(
                "textDocument/didSave",
                {"textDocument": {"uri": uri}, "text": mutated},
            )
            elapsed, mypy_diags = _wait_for_mypy_diagnostics(client, uri, timeout=8.0)
            latencies.append(elapsed)
            if mypy_diags:
                plugin_loaded = True
            pylsp_errors = sum(1 for d in mypy_diags if d.get("severity", 1) == 1)

            oracle = subprocess.run(
                ["dmypy", "run", "--", str(init_py)],
                cwd=seed_python_root,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if oracle.returncode not in (0, 1):  # 0=clean, 1=errors found; >=2 = daemon failure
                dmypy_errors.append(f"step={version} rc={oracle.returncode} stderr={oracle.stderr[:200]!r}")
            oracle_errors = sum(1 for line in oracle.stdout.splitlines() if ": error:" in line)
            pairs.append((oracle_errors, pylsp_errors))
    finally:
        init_py.write_text(original, encoding="utf-8")
        try:
            subprocess.run(["dmypy", "stop"], cwd=seed_python_root, capture_output=True, timeout=10, check=False)
        except Exception:
            pass
        client.shutdown()

    total = len(pairs)
    stale_count = sum(1 for o, p in pairs if o != p)
    stale_rate = stale_count / total if total else 0.0
    p95 = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies)

    if not plugin_loaded:
        outcome = "INDETERMINATE - pylsp-mypy never published mypy-sourced diagnostics; plugin-load failure"
    elif dmypy_errors:
        outcome = f"C - dmypy oracle failures ({len(dmypy_errors)}/{total}); cache/daemon corruption signal"
    elif stale_rate < 0.05 and p95 < 1.0:
        outcome = "A - stale_rate < 5% AND p95 < 1s - SHIP with pylsp-mypy in active set"
    elif stale_rate < 0.05 and p95 < 3.0:
        outcome = "B - stale_rate < 5% AND p95 1-3s - SHIP with documented warning"
    else:
        outcome = "C - stale_rate >= 5% OR p95 >= 3s - DROP pylsp-mypy at MVP; basedpyright sole type-error source"

    body = (
        f"# P5a - pylsp-mypy stale-rate under live_mode:false + dmypy:true\n\n"
        f"**Outcome:** {outcome}\n\n"
        f"**Evidence:**\n\n"
        f"- Total internal apply-equivalent steps: {total}\n"
        f"- pylsp-mypy plugin loaded (mypy-sourced diagnostic observed): {plugin_loaded}\n"
        f"- Stale steps (oracle != pylsp-mypy): {stale_count}\n"
        f"- Stale rate: {stale_rate:.2%}\n"
        f"- Latencies (s, all 12): {[round(x, 4) for x in latencies]!r}\n"
        f"- p95 latency (s): {p95:.3f}\n"
        f"- (oracle_errors, pylsp_errors) pairs: {pairs!r}\n"
        f"- dmypy oracle failures: {dmypy_errors!r}\n\n"
        f"**Configuration (per Q1 resolution):**\n\n"
        f"- pylsp-mypy: `live_mode: false`, `dmypy: true` (sent via both `initializationOptions` and `workspace/didChangeConfiguration`).\n"
        f"- Each step writes the mutated file to disk, sends `didChange` (full sync), then `didSave({{includeText: true}})`.\n"
        f"- Oracle: `dmypy run -- <file>` invoked from `seed_python_root` after each step (warm daemon after step 1).\n\n"
        f"**Wrapper-gap findings:**\n\n"
        f"- `_pylsp_client.PylspClient` extended with `diagnostics_by_uri` capture for this spike "
        f"(last-write-wins per URI). Mirrors the `_ruff_client.RuffClient.diagnostics` capture pattern.\n"
        f"- `workspace/didChangeConfiguration` plumbing must be re-implemented in Stage 1E `PylspServer` "
        f"adapter; SolidLanguageServer has no facade for `notify_did_change_configuration`.\n\n"
        f"**Decision:**\n\n"
        f"- A -> ship pylsp-mypy with `live_mode: false` + `dmypy: true` in MVP active server set.\n"
        f"- B -> ship with `CHANGELOG.md` note 'expect occasional latency >1s on first didSave after long idle'.\n"
        f"- C -> drop pylsp-mypy from MVP active set; update `python_strategy.py` and `multi_server.py` accordingly. "
        f"basedpyright remains authoritative for `severity_breakdown` per MVP §11.1.\n"
        f"- INDETERMINATE -> file pylsp-mypy plugin-load failure as Phase 0 finding; Stage 1E must investigate before activating.\n"
    )
    out = write_spike_result(results_dir, "P5a", body)
    print(f"\n[P5a] Outcome: {outcome}; wrote {out}")
    print(f"[P5a] stale_rate={stale_rate:.2%} p95={p95:.3f}s plugin_loaded={plugin_loaded}")
    print(f"[P5a] pairs={pairs}")
    assert outcome
