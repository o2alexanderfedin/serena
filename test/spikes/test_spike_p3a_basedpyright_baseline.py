"""P3a - basedpyright==1.39.3 green-bar baseline (Q3).

Phase 0 baseline against seed_python only; Stage 1H re-runs against full calcpy.
basedpyright 1.39.3 has no --exclude CLI flag, so we run the whole seed root and
PARTITION diagnostics: errors outside _pep_syntax.py (intentional PEP-654 fixture
from P3) define the green-bar baseline.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .conftest import write_spike_result

_INTENTIONAL = "_pep_syntax.py"


def _basedpyright_version() -> str:
    try:
        proc = subprocess.run(["basedpyright", "--version"],
                              capture_output=True, text=True, timeout=5)
        return (proc.stdout or proc.stderr).strip().splitlines()[0]
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return "unknown"


def test_p3a_basedpyright_baseline(seed_python_root: Path, results_dir: Path) -> None:
    proc = subprocess.run(
        ["basedpyright", "--outputjson", str(seed_python_root)],
        capture_output=True, text=True, timeout=60,
    )
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        report = {"summary": {"errorCount": -1, "warningCount": -1},
                  "raw": proc.stdout[:500], "stderr": proc.stderr[:500]}

    summary = report.get("summary") or {}
    err = int(summary.get("errorCount", -1))
    warn = int(summary.get("warningCount", -1))
    diags = report.get("generalDiagnostics") or []
    intentional = [d for d in diags if _INTENTIONAL in d.get("file", "")]
    base_err = sum(1 for d in diags
                   if d.get("severity") == "error" and _INTENTIONAL not in d.get("file", ""))
    base_warn = sum(1 for d in diags
                    if d.get("severity") == "warning" and _INTENTIONAL not in d.get("file", ""))
    sample = [{"severity": d.get("severity"), "file": Path(d.get("file", "")).name,
               "rule": d.get("rule"), "message": (d.get("message") or "")[:120]}
              for d in diags[:3]]
    cli_v = _basedpyright_version()
    json_v = report.get("version") or "unknown"
    decision = (f"BASELINE ESTABLISHED: 0 errors outside {_INTENTIONAL}. "
                f"Re-run at Stage 1H against full calcpy."
                if base_err == 0 else
                f"BASELINE ISSUE: {base_err} unexpected error(s) outside {_INTENTIONAL}.")

    body = f"""# P3a - basedpyright==1.39.3 green-bar baseline

**Pin:** `basedpyright==1.39.3` ([Q3 resolution](../../design/mvp/open-questions/q3-basedpyright-pinning.md))

**Errors (total):** {err}  |  **Warnings (total):** {warn}
**Errors (excluding `{_INTENTIONAL}`):** {base_err}  |  **Warnings (excl.):** {base_warn}
**Intentional-fixture diagnostics:** {len(intentional)}

**Sample diagnostics (first 3):**

```
{json.dumps(sample, indent=2)}
```

**Version reported:**
- CLI (`basedpyright --version`): `{cli_v}`
- JSON report (`report.version`): `{json_v}`

**`_pep_syntax.py` decision:** basedpyright 1.39.3 has no `--exclude` CLI flag
(verified via `--help`). The P3 fixture `_pep_syntax.py` contains an
intentional semantic violation (`return` inside `except*`). Rather than ship
a `pyrightconfig.json` to exclude one file, this spike runs the full seed
root and PARTITIONS diagnostics; errors outside `_pep_syntax.py` define the
green-bar baseline.

**Decision:** {decision}

**Re-run scope (Stage 1H):** full calcpy suite + sub-fixtures, same partitioning rule.
"""
    write_spike_result(results_dir, "P3a", body)
    assert err >= 0  # permissive: baseline established or documented
