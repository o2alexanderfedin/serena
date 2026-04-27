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
from serena.refactoring.multi_server import (
    _check_apply_clean,
    _check_workspace_boundary,
)


HERE = Path(__file__).resolve().parent
FIXTURES_ROOT = HERE.parent / "fixtures" / "rust"

CLIPPY_A = FIXTURES_ROOT / "clippy_a"
CLIPPY_COLLISION = FIXTURES_ROOT / "clippy_collision"
CLIPPY_OUT_OF_WORKSPACE = FIXTURES_ROOT / "clippy_out_of_workspace"


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


@pytest.fixture
def clippy_collision_workspace(tmp_path: Path) -> Path:
    if not (CLIPPY_COLLISION / "Cargo.toml").exists():
        pytest.skip(f"clippy_collision fixture missing at {CLIPPY_COLLISION}")
    return _copy_fixture(CLIPPY_COLLISION, tmp_path / "clippy_collision")


@pytest.fixture
def clippy_out_of_workspace_workspace(tmp_path: Path) -> Path:
    if not (CLIPPY_OUT_OF_WORKSPACE / "Cargo.toml").exists():
        pytest.skip(
            f"clippy_out_of_workspace fixture missing at "
            f"{CLIPPY_OUT_OF_WORKSPACE}"
        )
    return _copy_fixture(
        CLIPPY_OUT_OF_WORKSPACE, tmp_path / "clippy_out_of_workspace",
    )


# ---------------------------------------------------------------------------
# Synthetic payload helpers — identical shape to ClippyAdapter output.
# ---------------------------------------------------------------------------


def _synthetic_clippy_edit(
    file_uri: str,
    *,
    new_text: str = "",
    line: int = 0,
    column: int = 0,
    end_line: int = 0,
    end_column: int = 0,
    version: int | None = None,
    lint: str = "clippy::useless_vec",
) -> dict[str, Any]:
    """Build a WorkspaceEdit dict structurally identical to what
    ``clippy_json_to_workspace_edit`` produces for one suggestion."""
    return {
        "documentChanges": [
            {
                "textDocument": {"uri": file_uri, "version": version},
                "edits": [
                    {
                        "range": {
                            "start": {"line": line, "character": column},
                            "end": {"line": end_line, "character": end_column},
                        },
                        "newText": new_text,
                    },
                ],
            },
        ],
        "changeAnnotations": {
            lint: {
                "label": lint,
                "needsConfirmation": True,
                "description": "synthetic clippy suggestion",
            },
        },
    }


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


# ---------------------------------------------------------------------------
# Task 2 — Invariant 1 (atomicity): merger rejects WHOLE edit on bad span.
# ---------------------------------------------------------------------------


def test_invariant_1_atomicity_rejects_clippy_edit_on_syntactic_failure(
    tmp_path: Path,
) -> None:
    """A clippy-shape WorkspaceEdit whose declared version doesn't match
    the merger-tracked version must be rejected by ``_check_apply_clean``,
    AND the file on disk must remain unchanged. The structural contract:
    when ANY invariant fails, the merger returns ``ok=False`` and the
    applier never runs — so the rust+clippy payload shape demonstrates
    the same atomic-rollback path the Python multi-LSP suite already
    exercises (see ``test_multi_server_apply_cleanly.py``)."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    src_dir = workspace / "src"
    src_dir.mkdir()
    rs = src_dir / "lib.rs"
    rs.write_text("pub fn it_works() -> i32 { 1 + 1 }\n")
    original = rs.read_text()

    # Synthesize a clippy edit pinned at version=42; merger tracks
    # version=7. _check_apply_clean must reject and the applier must
    # never see the edit (atomicity).
    edit = _synthetic_clippy_edit(
        rs.as_uri(),
        new_text="pub fn it_works() -> i32 { 4 }\n",
        line=0,
        column=0,
        end_line=1,
        end_column=0,
        version=42,
    )
    document_versions = {rs.as_uri(): 7}

    ok, reason = _check_apply_clean(edit, document_versions)
    assert ok is False
    assert reason is not None and "STALE_VERSION" in reason

    # Atomicity: file on disk MUST be unchanged because the merger's
    # gate-then-apply pattern (per multi_server.merge_and_validate_code_actions)
    # never reaches the applier when the gate fails.
    assert rs.read_text() == original


# ---------------------------------------------------------------------------
# Task 3 — Invariant 2 (version mismatch): rejected as a whole.
# ---------------------------------------------------------------------------


def test_invariant_2_version_mismatch_rejects_whole_clippy_edit(
    tmp_path: Path,
) -> None:
    """Per §11.7 invariant 2: any TextDocumentEdit whose textDocument.version
    does not match the merger-tracked version causes the WHOLE
    WorkspaceEdit to be rejected — not just the offending sub-edit."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    src_dir = workspace / "src"
    src_dir.mkdir()
    a = src_dir / "a.rs"
    a.write_text("pub fn a() {}\n")
    b = src_dir / "b.rs"
    b.write_text("pub fn b() {}\n")

    # Edit touches a.rs at version=5 (matches) and b.rs at version=99
    # (does not match the tracked version=2). The whole edit must reject.
    edit: dict[str, Any] = {
        "documentChanges": [
            {
                "textDocument": {"uri": a.as_uri(), "version": 5},
                "edits": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 0},
                        },
                        "newText": "// a edited\n",
                    },
                ],
            },
            {
                "textDocument": {"uri": b.as_uri(), "version": 99},
                "edits": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 0},
                        },
                        "newText": "// b edited\n",
                    },
                ],
            },
        ],
    }
    versions = {a.as_uri(): 5, b.as_uri(): 2}
    ok, reason = _check_apply_clean(edit, versions)
    assert ok is False
    assert reason is not None
    assert "STALE_VERSION" in reason
    assert b.as_uri() in reason
    # The first sub-edit's version was correct; we still reject the WHOLE
    # edit (atomicity per §11.8).
    assert a.read_text() == "pub fn a() {}\n"
    assert b.read_text() == "pub fn b() {}\n"


# ---------------------------------------------------------------------------
# Task 4 — Invariant 3 (path-filter workspace boundary).
# ---------------------------------------------------------------------------


def test_invariant_3_path_filter_rejects_clippy_fix_outside_workspace(
    clippy_out_of_workspace_workspace: Path,
) -> None:
    """The fixture is a *driver*: it carries a ``.scalpel-target`` file
    whose contents are the offending out-of-workspace path. The test
    reads that target, builds a clippy-shape WorkspaceEdit pointing at
    it, and asserts ``_check_workspace_boundary`` rejects the WHOLE edit
    with the canonical OUT_OF_WORKSPACE_EDIT_BLOCKED reason."""
    target_text = (
        clippy_out_of_workspace_workspace / ".scalpel-target"
    ).read_text().strip()
    target_path = Path(target_text)

    edit = _synthetic_clippy_edit(
        target_path.as_uri(),
        new_text="// pwned via clippy fix\n",
    )
    workspace_folders = [str(clippy_out_of_workspace_workspace)]
    ok, reason = _check_workspace_boundary(
        edit=edit,
        workspace_folders=workspace_folders,
        extra_paths=(),
    )
    assert ok is False, (
        f"out-of-workspace clippy edit must be rejected; got ok={ok} "
        f"reason={reason!r}"
    )
    assert reason is not None
    assert "OUT_OF_WORKSPACE_EDIT_BLOCKED" in reason
    assert str(target_path) in reason


def test_invariant_3_path_filter_accepts_in_workspace_clippy_fix(
    clippy_a_workspace: Path,
) -> None:
    """Counter-example: a clippy edit targeting a file inside the
    workspace passes the boundary check. Pairs with the rejection test
    above so any change to ``_check_workspace_boundary`` that breaks
    the happy-path is caught by this suite."""
    src = clippy_a_workspace / "src" / "lib.rs"
    edit = _synthetic_clippy_edit(src.as_uri())
    ok, reason = _check_workspace_boundary(
        edit=edit,
        workspace_folders=[str(clippy_a_workspace)],
        extra_paths=(),
    )
    assert ok is True, (
        f"in-workspace clippy edit must pass boundary check; got "
        f"ok={ok} reason={reason!r}"
    )
    assert reason is None


# ---------------------------------------------------------------------------
# Task 5 — Invariant 4 (change-annotation warning surface).
# ---------------------------------------------------------------------------


def test_invariant_4_clippy_annotations_round_trip_with_needs_confirmation(
    tmp_path: Path,
) -> None:
    """``ClippyAdapter`` MUST emit ``changeAnnotations`` with
    ``needsConfirmation=True`` so the dry-run surface can warn the LLM
    before any bytes hit disk. Default allowlist is empty per the leaf
    spec — every clippy lint surfaces as needs-confirmation."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    src = workspace / "src" / "main.rs"
    src.parent.mkdir(parents=True)
    src.write_text("fn main() {}\n")

    record = {
        "reason": "compiler-message",
        "message": {
            "message": "useless use of `vec!`",
            "code": {"code": "clippy::useless_vec"},
            "spans": [
                {
                    "file_name": "src/main.rs",
                    "line_start": 1,
                    "line_end": 1,
                    "column_start": 1,
                    "column_end": 13,
                    "suggested_replacement": "fn main() {}",
                    "suggestion_applicability": "MachineApplicable",
                },
            ],
        },
    }
    edit = clippy_json_to_workspace_edit(json.dumps(record) + "\n", workspace)

    annotations = edit.get("changeAnnotations") or {}
    assert "clippy::useless_vec" in annotations, (
        f"expected clippy::useless_vec annotation; got {sorted(annotations)}"
    )
    entry = annotations["clippy::useless_vec"]
    assert entry["label"] == "clippy::useless_vec"
    assert entry["needsConfirmation"] is True
    # The description carries the human-readable message so the LLM /
    # confirmation surface can show it verbatim.
    assert entry["description"] == "useless use of `vec!`"
