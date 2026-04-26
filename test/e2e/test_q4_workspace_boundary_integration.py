"""Q4 workspace-boundary integration tests.

Per scope-report S15.4b — three integration sub-tests against the
Stage 1A `is_in_workspace` + Stage 1A workspace-boundary helpers.

Note: ``ScalpelRuntime.editor_for_workspace`` and
``editor.try_apply_workspace_edit`` are not exposed in Stage 2A. We
exercise the public surface available today (the facades' own
boundary guard) plus the Stage 1A `is_in_workspace` helper that
underpins it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from solidlsp.ls import SolidLanguageServer
from serena.tools.scalpel_runtime import parse_workspace_extra_paths


def _is_in_workspace(
    target: Path, roots: list[Path], extra_paths: tuple[str, ...] = ()
) -> bool:
    """Stage 1A SolidLanguageServer.is_in_workspace static helper."""
    return SolidLanguageServer.is_in_workspace(
        str(target),
        [str(r) for r in roots],
        extra_paths=list(extra_paths),
    )


@pytest.mark.e2e
def test_q4_in_workspace_paths_admit(
    calcrs_e2e_root: Path,
) -> None:
    """Paths under the workspace root are admitted by the boundary check."""
    src = calcrs_e2e_root / "src" / "lib.rs"
    assert _is_in_workspace(src, [calcrs_e2e_root])
    nested = calcrs_e2e_root / "src" / "deeper" / "x.rs"
    assert _is_in_workspace(nested, [calcrs_e2e_root])


@pytest.mark.e2e
def test_q4_registry_path_rejected_by_boundary(
    calcrs_e2e_root: Path,
    tmp_path: Path,
) -> None:
    """A path under tmp_path/registry/ (out-of-workspace) must NOT be
    admitted by the boundary check (S11.8 path-filter contract).
    """
    out = tmp_path / "registry" / "fakelib-1.0.0" / "src" / "lib.rs"
    assert not _is_in_workspace(out, [calcrs_e2e_root])


@pytest.mark.e2e
def test_q4_extra_paths_opt_in_admits_vendored(
    calcrs_e2e_root: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Setting O2_SCALPEL_WORKSPACE_EXTRA_PATHS=<dir> admits paths under
    that dir without modifying the workspace_folders list.
    """
    vendored = tmp_path / "vendored_dep"
    vendored.mkdir(parents=True, exist_ok=True)
    out = vendored / "lib.rs"

    # Without EXTRA_PATHS: rejected.
    monkeypatch.delenv("O2_SCALPEL_WORKSPACE_EXTRA_PATHS", raising=False)
    assert parse_workspace_extra_paths() == ()
    assert not _is_in_workspace(out, [calcrs_e2e_root])

    # With EXTRA_PATHS pointing at the vendored dir: admitted.
    monkeypatch.setenv("O2_SCALPEL_WORKSPACE_EXTRA_PATHS", str(vendored))
    extras = parse_workspace_extra_paths()
    assert str(vendored) in extras
    assert _is_in_workspace(out, [calcrs_e2e_root], extra_paths=extras)


@pytest.mark.e2e
def test_q4_facade_rejects_out_of_workspace_atomically(
    mcp_driver_python,
    calcpy_e2e_root: Path,
    tmp_path: Path,
) -> None:
    """Facade-level integration: a refactor whose source file is out of
    workspace is atomically rejected by the boundary guard before any
    Rope / LSP traffic. The in-workspace file is not modified.
    """
    in_src = calcpy_e2e_root / "calcpy" / "calcpy.py"
    pre_bytes = in_src.read_bytes()

    outside_src = tmp_path / "elsewhere" / "other.py"
    outside_src.parent.mkdir(parents=True, exist_ok=True)
    outside_src.write_text("def bar():\n    return 0\n")

    result_json = mcp_driver_python.split_file(
        file=str(outside_src),
        groups={"a": ["bar"]},
        parent_layout="file",
        dry_run=False,
        language="python",
        allow_out_of_workspace=False,
    )
    payload = json.loads(result_json)
    assert payload.get("applied") is False, payload
    failure = payload.get("failure") or {}
    assert failure.get("code") in (
        "WORKSPACE_BOUNDARY_VIOLATION",
        "OUT_OF_WORKSPACE_EDIT_BLOCKED",
    ), f"expected boundary failure; got {failure}"
    assert in_src.read_bytes() == pre_bytes, "atomic-reject violated"
