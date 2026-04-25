"""S2 - snippetTextEdit:false honored by rust-analyzer assists.

A: 0 offenders -> defensive `$N` strip is sufficient (~0 LoC).
B: >=1 offender -> mandatory regex strip path required (+50 LoC).
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("CARGO_BUILD_RUSTC", "rustc")  # neutralize rust-fv-driver alias

from solidlsp.language_servers.rust_analyzer import RustAnalyzer
from solidlsp.ls import SolidLanguageServer
from solidlsp.ls_config import Language, LanguageServerConfig

from .conftest import write_spike_result

# Catches `$0`/`$1` placeholders AND `${0:label}` / `${1|a,b|}` choice forms.
SNIPPET_RE = re.compile(r"\$\d+|\$\{\d+")


def _patched_init_params(repository_absolute_path: str) -> Any:
    """Flip experimental.snippetTextEdit -> False on the otherwise-stock rust-analyzer init."""
    params = RustAnalyzer._get_initialize_params(repository_absolute_path)
    caps = params.get("capabilities", {})  # type: ignore[union-attr]
    if isinstance(caps, dict):
        caps.setdefault("experimental", {})["snippetTextEdit"] = False
    return params


def _scan_edit_for_snippets(action: dict[str, Any], offenders: list[dict[str, Any]]) -> None:
    edit = action.get("edit") if isinstance(action.get("edit"), dict) else {}
    text_edits: list[dict[str, Any]] = []
    for tde in edit.get("documentChanges") or []:
        if isinstance(tde, dict):
            text_edits.extend(e for e in (tde.get("edits") or []) if isinstance(e, dict))
    for edits in (edit.get("changes") or {}).values():
        text_edits.extend(e for e in (edits or []) if isinstance(e, dict))
    for te in text_edits:
        new_text = te.get("newText", "") or ""
        if SNIPPET_RE.search(new_text):
            offenders.append({"title": action.get("title"), "newText": new_text[:200]})


def test_s2_snippet_false(seed_rust_root: Path, results_dir: Path) -> None:
    cfg = LanguageServerConfig(code_language=Language.RUST)
    srv = SolidLanguageServer.create(cfg, str(seed_rust_root))
    srv._get_initialize_params = staticmethod(_patched_init_params)  # type: ignore[attr-defined,method-assign]

    actions: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []
    offenders: list[dict[str, Any]] = []

    # Sweep ranges across all lib.rs symbols (fns, struct, impl, mod, use, tests) to maximize assists.
    sweep: list[dict[str, Any]] = [
        {"start": {"line": s, "character": 0}, "end": {"line": e, "character": c}}
        for (s, e, c) in [
            (0, 0, 10), (0, 2, 1), (4, 6, 1), (8, 8, 16), (9, 11, 5),
            (13, 16, 5), (18, 22, 5), (25, 25, 22), (27, 35, 1), (0, 35, 0),
        ]
    ]

    with srv.start_server():
        time.sleep(3.0)  # cold-start indexing
        with srv.open_file("src/lib.rs"):
            time.sleep(1.5)
            uri = (seed_rust_root / "src" / "lib.rs").as_uri()
            for rng in sweep:
                raw = srv.server.send_request(
                    "textDocument/codeAction",
                    {"textDocument": {"uri": uri}, "range": rng, "context": {"diagnostics": []}},
                ) or []
                actions.extend(a for a in raw if isinstance(a, dict))
            # rust-analyzer returns deferred-resolution actions (S3); resolve before inspection.
            for a in actions:
                try:
                    r = srv.server.send_request("codeAction/resolve", a)
                except Exception:
                    r = a
                resolved.append(r if isinstance(r, dict) else a)
            for a in resolved:
                _scan_edit_for_snippets(a, offenders)

    outcome = (
        f"B - {len(offenders)} assist(s) emit `$N` markers despite snippetTextEdit:false; mandatory strip required"
        if offenders
        else f"A - 0 of {len(resolved)} resolved actions emit snippet markers; defensive strip is sufficient"
    )
    offenders_blob = "\n".join(f"- `{o['title']}`: {o['newText']!r}" for o in offenders) or "_(none)_"
    body = (
        f"# S2 - snippetTextEdit:false honored by rust-analyzer assists\n\n"
        f"**Outcome:** {outcome}\n\n**Evidence:**\n\n"
        f"- Code actions surfaced (10-range sweep over lib.rs): {len(actions)}\n"
        f"- Resolved actions (after `codeAction/resolve`): {len(resolved)}\n"
        f"- Snippet-marker offenders (`$N` / `${{N`): {len(offenders)}\n"
        f"- Capability advertised: `experimental.snippetTextEdit = false` (instance monkey-patch of "
        "`RustAnalyzer._get_initialize_params`)\n\n"
        f"**Offenders:**\n\n{offenders_blob}\n\n"
        "**API audit (2026-04-24):**\n\n"
        "- Fork hard-codes `experimental.snippetTextEdit: True` at `rust_analyzer.py:458`. NO public "
        "capability-override hook on `SolidLanguageServer`/`RustAnalyzer`; spike monkey-patches "
        "`_get_initialize_params` pre-`start_server()`. Stage 1A must expose a per-language capability "
        "override so scalpel advertises `false`.\n"
        "- Deferred-resolution code actions (S3): every action MUST go through `codeAction/resolve` "
        "before `edit:` is materialized.\n"
        "- Snippet regex `r\"\\$\\d+|\\$\\{\\d+\"` covers `$0` placeholders + `${0:label}` / `${1|a,b|}` choices.\n\n"
        "**Decision:**\n\n"
        "- A -> defensive `$N` strip in applier (~10 LoC) suffices; no extra work.\n"
        "- B -> mandatory regex strip path with placeholder/choice/escape edge-cases (+50 LoC).\n"
    )
    out = write_spike_result(results_dir, "S2", body)
    print(f"\n[S2] Outcome: {outcome}")
    print(f"[S2] Wrote: {out}")
    print(f"[S2] raw={len(actions)} resolved={len(resolved)} offenders={len(offenders)}")
    for o in offenders[:5]:
        print(f"[S2] OFFENDER: {o['title']!r} -> {o['newText']!r}")
    assert outcome
