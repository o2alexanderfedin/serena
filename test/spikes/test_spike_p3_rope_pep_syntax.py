"""P3 - Rope vs PEP 695 / PEP 701 / PEP 654.

Does Rope's parser handle 3.12+ syntax? Plan illustrative code uses `ast.parse`
(stdlib, not Rope). This test opens the fixture against pylsp + pylsp-rope:
(a) `source: 'pylsp'` syntax-error on a PEP line = parse stack rejected; (b)
`pylsp_rope.refactor.extract_method` errors with 'syntax/parse/rope' = Rope
parse fault. Wrapper-gap: PYTHON adapter is Pyright -- raw stdio via
`_pylsp_client.PylspClient` (P1/P2/P5a pattern).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from ._pylsp_client import PylspClient
from .conftest import write_spike_result

PEP695_LINE = 9   # 0-indexed `type IntList = list[int]`
PEP701_LINE = 13  # 0-indexed `    return f"hello {f"{name}"}"`
PEP654_LINE = 19  # 0-indexed `    except* (TypeError, ValueError) as eg:`


def _is_parse_error(diagnostics: list[dict], line0: int) -> str:
    for d in diagnostics:
        if d.get("range", {}).get("start", {}).get("line") != line0:
            continue
        msg = (d.get("message") or "").lower()
        if (d.get("source") or "").lower() == "pylsp" and "syntax" in msg:
            return f"parse-error: {d.get('message')!r}"
    return "ok"


def _classify(parse: str, extract_err: str | None) -> str:
    if parse.startswith("parse-error"):
        return parse
    if extract_err and any(k in extract_err.lower() for k in ("syntax", "parse", "rope")):
        return f"extract-error: {extract_err!r}"
    return "ok"


def test_p3_rope_pep_syntax(seed_python_root: Path, results_dir: Path) -> None:
    runtime = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    pep_file = seed_python_root / "calcpy_seed" / "_pep_syntax.py"
    src = pep_file.read_text(encoding="utf-8")
    uri = pep_file.as_uri()

    if sys.version_info < (3, 12):
        body = (
            f"# P3 - Rope vs PEP 695 / 701 / 654 syntax\n\n"
            f"**Outcome:** INDETERMINATE - runtime Python {runtime} < 3.12 "
            f"(fixture file does not parse on this build).\n\n**Runtime:** Python {runtime}\n"
        )
        write_spike_result(results_dir, "P3", body)
        assert "INDETERMINATE"
        return

    client = PylspClient(seed_python_root)
    rope_loaded = False
    diagnostics: list[dict] = []
    err_695 = err_701 = err_654 = None
    try:
        init = client.request("initialize", {
            "processId": None, "rootUri": seed_python_root.as_uri(),
            "capabilities": {"workspace": {"applyEdit": True, "workspaceEdit": {"documentChanges": True}}},
        }, timeout=15.0)
        client.notify("initialized", {})
        cmds = init.get("result", {}).get("capabilities", {}).get("executeCommandProvider", {}).get("commands", [])
        rope_loaded = any(c.startswith("pylsp_rope.") for c in cmds)
        client.notify("textDocument/didOpen", {
            "textDocument": {"uri": uri, "languageId": "python", "version": 0, "text": src}})
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline and uri not in client.diagnostics_by_uri:
            time.sleep(0.1)
        diagnostics = list(client.diagnostics_by_uri.get(uri, []))

        def extract(sl: int, sc: int, el: int, ec: int) -> str | None:
            try:
                resp = client.request("workspace/executeCommand", {
                    "command": "pylsp_rope.refactor.extract_method",
                    "arguments": [{"document_uri": uri,
                                   "range": {"start": {"line": sl, "character": sc},
                                             "end": {"line": el, "character": ec}},
                                   "name": "extracted", "global_": False, "similar": False}],
                }, timeout=10.0)
                return (resp.get("error") or {}).get("message")
            except Exception as exc:  # noqa: BLE001
                return repr(exc)

        err_695 = extract(PEP695_LINE, 0, PEP695_LINE, 24)
        err_701 = extract(PEP701_LINE, 4, PEP701_LINE, 30)
        err_654 = extract(PEP654_LINE - 1, 8, PEP654_LINE - 1, 25)
    finally:
        client.shutdown()

    o_695 = _classify(_is_parse_error(diagnostics, PEP695_LINE), err_695)
    o_701 = _classify(_is_parse_error(diagnostics, PEP701_LINE), err_701)
    o_654 = _classify(_is_parse_error(diagnostics, PEP654_LINE), err_654)
    all_pass = all(o == "ok" for o in (o_695, o_701, o_654))
    decision = ("All-pass -> declare Python 3.10-3.13+ supported." if all_pass else
                "At least one PEP failed -> support Python 3.10-3.12; pin Rope; 3.13+ best-effort.")

    body = (
        f"# P3 - Rope vs PEP 695 / 701 / 654 syntax\n\n"
        f"**Per-PEP outcome:**\n\n"
        f"- PEP 695 (type aliases, line {PEP695_LINE + 1}): {o_695}\n"
        f"- PEP 701 (nested f-strings, line {PEP701_LINE + 1}): {o_701}\n"
        f"- PEP 654 (except groups, line {PEP654_LINE + 1}): {o_654}\n\n"
        f"**Runtime:** Python {runtime} (>=3.12: {sys.version_info >= (3, 12)})\n"
        f"**pylsp-rope plugin loaded:** {rope_loaded}\n\n"
        f"**Evidence:**\n\n"
        f"- diagnostics published: {len(diagnostics)}\n"
        f"- extract_method errors: PEP695={err_695!r}; PEP701={err_701!r}; PEP654={err_654!r}\n"
        f"- raw diagnostics: {diagnostics!r}\n\n"
        f"**Decision:** {decision}\n\n"
        "**Signal vs noise:**\n\n"
        "- `source: 'pylsp'` + 'syntax' on a PEP line = parse stack rejected.\n"
        "- extract errors w/ 'syntax'/'parse'/'rope' = Rope fault; generic semantic refusals do not count.\n"
        "- mypy `return in except*` = SEMANTIC (mypy parsed it), not parse failure.\n"
    )
    out = write_spike_result(results_dir, "P3", body)
    print(f"\n[P3] PEP695={o_695} PEP701={o_701} PEP654={o_654} runtime={runtime} rope_loaded={rope_loaded}")
    print(f"[P3] wrote {out}")
    assert o_695 and o_701 and o_654
