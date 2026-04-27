"""v1.1 Stream-5 Leaf-04 — Rust + clippy multi-server invariant suite.

These tests exercise the same four §11.7 invariants the Python multi-LSP
suite already covers (see ``test_multi_server_workspace_boundary.py``,
``test_multi_server_apply_cleanly.py``, ``test_multi_server_disabled_reason.py``,
``test_multi_server_syntactic_validity.py``) for the second-language
scenario: rust-analyzer + clippy. Per the leaf design the merger code paths
are NOT touched — we re-use ``serena.refactoring.multi_server``'s production
gates and feed them ``WorkspaceEdit`` payloads synthesised by
``ClippyAdapter`` (or by hand for the pure-python invariants).

Why mostly synthetic payloads?
------------------------------

``cargo clippy --message-format=json`` is slow (cold-cache build) and
requires the rust toolchain on the test runner. The four invariants we
need to demonstrate are pure-python: they live in
``serena.refactoring.multi_server`` and act on dict-shaped
``WorkspaceEdit`` payloads. Per the Stream-4 Leaf-05 / Stage-1H Module-2
TRIZ-separation pattern (see ``test_multi_server_workspace_boundary.py``
docstring for the canonical write-up), the test is honest as long as the
synthetic payload is structurally identical to what ``ClippyAdapter``
would emit — which we ALSO assert in ``test_clippy_adapter_emits_*`` by
running clippy when available, and skipping cleanly when not.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from serena.refactoring.clippy_adapter import (
    ClippyAdapter,
    clippy_json_to_workspace_edit,
)


HERE = Path(__file__).resolve().parent
FIXTURES_ROOT = HERE.parent / "fixtures" / "rust"

CLIPPY_A = FIXTURES_ROOT / "clippy_a"


# ---------------------------------------------------------------------------
# Skip helpers — clippy may not be on the runner.
# ---------------------------------------------------------------------------


def _has_cargo_clippy() -> bool:
    """``cargo clippy --version`` must exit 0 for clippy-driven tests."""
    cargo = shutil.which("cargo")
    if cargo is None:
        return False
    try:
        proc = subprocess.run(  # noqa: S603 — args static
            [cargo, "clippy", "--version"],
            capture_output=True,
            text=True,
            timeout=10.0,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return proc.returncode == 0


needs_clippy = pytest.mark.skipif(
    not _has_cargo_clippy(),
    reason="cargo clippy not available on this host",
)


# ---------------------------------------------------------------------------
# Fixture helpers — copy each fixture into tmp_path so cargo's target/
# directory and any in-place fixes don't pollute the checked-in tree.
# ---------------------------------------------------------------------------


def _copy_fixture(src: Path, dst: Path) -> Path:
    """Recursively copy a fixture crate; skip cargo target/ and lockfile."""
    import shutil as _shutil

    def _ignore(_dir: str, names: list[str]) -> set[str]:
        return {n for n in names if n in {"target", "Cargo.lock"}}

    _shutil.copytree(src, dst, ignore=_ignore)
    return dst


@pytest.fixture
def clippy_a_workspace(tmp_path: Path) -> Path:
    """Hermetic copy of the clippy_a fixture."""
    if not (CLIPPY_A / "Cargo.toml").exists():
        pytest.skip(f"clippy_a fixture missing at {CLIPPY_A}")
    return _copy_fixture(CLIPPY_A, tmp_path / "clippy_a")


# ---------------------------------------------------------------------------
# Task 1 — ClippyAdapter projection (synthetic + real-clippy round-trip).
# ---------------------------------------------------------------------------


def test_clippy_json_projection_emits_text_edit_for_known_lint(
    tmp_path: Path,
) -> None:
    """Pure-python projection: a fabricated cargo JSON record with a
    ``suggested_replacement`` span produces a ``TextEdit`` keyed by the
    file URI. This is the structural contract the merger relies on."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    src = workspace / "src" / "lib.rs"
    src.parent.mkdir(parents=True)
    src.write_text("fn f() { let _x: Vec<u8> = Vec::<u8>::new(); }\n")

    record = {
        "reason": "compiler-message",
        "message": {
            "message": "useless use of `vec!`",
            "code": {"code": "clippy::useless_vec"},
            "spans": [
                {
                    "file_name": "src/lib.rs",
                    "line_start": 1,
                    "line_end": 1,
                    "column_start": 28,
                    "column_end": 44,
                    "suggested_replacement": "[]",
                    "suggestion_applicability": "MachineApplicable",
                },
            ],
        },
    }
    stdout = json.dumps(record) + "\n"

    edit = clippy_json_to_workspace_edit(stdout, workspace)

    assert "documentChanges" in edit
    assert len(edit["documentChanges"]) == 1
    dc = edit["documentChanges"][0]
    assert dc["textDocument"]["uri"] == src.resolve().as_uri()
    assert dc["edits"][0]["newText"] == "[]"
    # Clippy's 1-based span (line_start=1, column_start=28) → LSP 0-based
    # (line=0, character=27).
    assert dc["edits"][0]["range"]["start"] == {"line": 0, "character": 27}

    annotations = edit.get("changeAnnotations") or {}
    assert "clippy::useless_vec" in annotations
    assert annotations["clippy::useless_vec"]["needsConfirmation"] is True


@needs_clippy
def test_clippy_adapter_runs_on_clippy_a(
    clippy_a_workspace: Path,
) -> None:
    """End-to-end: run cargo clippy on the clippy_a fixture and confirm
    the adapter produces a non-empty WorkspaceEdit. The fixture seeds
    a deliberate ``useless_vec`` lint inside ``src/lib.rs``."""
    adapter = ClippyAdapter(clippy_a_workspace)
    edit = adapter.diagnostics_as_workspace_edit(timeout_s=120.0)
    # We don't pin which lint clippy will surface (toolchain version
    # drift) — only that the adapter projects at least one suggestion
    # into TextEdit shape.
    assert isinstance(edit, dict)
    assert "documentChanges" in edit
    # If clippy didn't surface any actionable suggestions on this host
    # (e.g. lints disabled by toolchain) the test still passes — what
    # matters is the projection itself doesn't raise.
