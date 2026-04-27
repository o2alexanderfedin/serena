"""Stage 1H smoke 1 — rust-analyzer offers at least one code action on calcrs.

Proves the harness boots rust-analyzer against the calcrs Cargo
workspace fixture and that the Stage 1A
``SolidLanguageServer.request_code_actions`` facade returns at least
one action.  The deferred-resolution shape (rust-analyzer publishes
``{title, kind, data}`` only) is part of what gets exercised — the
test asserts the surface, not the resolved edit.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from solidlsp.ls import SolidLanguageServer


def test_rust_analyzer_returns_code_actions_on_calcrs_lib(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    """rust-analyzer must offer >=1 code action on ``calcrs/src/lib.rs``."""
    lib_path = str(calcrs_workspace / "calcrs" / "src" / "lib.rs")
    assert Path(lib_path).is_file(), f"fixture file missing: {lib_path}"

    # Cold-start indexing on the workspace.  ~3 s is enough for the
    # 2-crate minimum-scope fixture; the spike S3 test uses the same
    # budget against the larger seed.
    time.sleep(3.0)

    # Compute a safe whole-file range via the shared helper.
    # rust-analyzer rejects positions past EOF (unlike ruff which
    # clamps), so we delegate to ``compute_file_range`` instead of
    # inlining the EOF coordinate math here.
    from solidlsp.util.file_range import compute_file_range

    _, file_end = compute_file_range(lib_path)

    actions: list[dict[str, Any]] = []
    with ra_lsp.open_file("calcrs/src/lib.rs"):
        time.sleep(1.0)
        # Probe a few representative ranges so at least one assist
        # surfaces — single point, function-signature span, whole-file.
        probes = [
            ({"line": 12, "character": 4}, {"line": 12, "character": 4}),  # inside `eval_const`
            ({"line": 11, "character": 0}, {"line": 14, "character": 1}),  # whole-fn span
            ({"line": 0, "character": 0}, file_end),                       # whole file
        ]
        for start, end in probes:
            raw = ra_lsp.request_code_actions(
                lib_path, start=start, end=end, diagnostics=[]
            )
            actions.extend(a for a in raw if isinstance(a, dict))

    assert actions, (
        "rust-analyzer returned zero code actions across 3 probe ranges; "
        "harness or fixture is broken."
    )

    # Per phase-0 S6, top-level shape is {title, kind, data, ...}; we
    # don't resolve here — just smoke the deferred-resolution surface.
    titles = [a.get("title") for a in actions if a.get("title")]
    assert titles, "actions returned but none carried a title field"
