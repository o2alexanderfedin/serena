"""Stage 2A T2 — facade_support.py shared helpers."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from serena.refactoring.capabilities import CapabilityRecord
from serena.tools.facade_support import (
    FACADE_TO_CAPABILITY_ID,
    apply_workspace_edit_via_editor,
    build_failure_result,
    record_checkpoint_for_workspace_edit,
    resolve_capability_for_facade,
    workspace_boundary_guard,
)
from serena.tools.scalpel_runtime import ScalpelRuntime
from serena.tools.scalpel_schemas import ErrorCode


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def test_facade_to_capability_id_table_covers_five_facades():
    expected = {
        "split_file",
        "extract",
        "inline",
        "rename",
        "imports_organize",
    }
    assert set(FACADE_TO_CAPABILITY_ID) == expected


def test_workspace_boundary_guard_passes_for_in_workspace_path(tmp_path):
    target = tmp_path / "src" / "x.py"
    target.parent.mkdir()
    target.write_text("")
    err = workspace_boundary_guard(
        file=str(target), project_root=tmp_path, allow_out_of_workspace=False,
    )
    assert err is None


def test_workspace_boundary_guard_rejects_out_of_workspace(tmp_path):
    outside = tmp_path.parent / "elsewhere.py"
    err = workspace_boundary_guard(
        file=str(outside), project_root=tmp_path, allow_out_of_workspace=False,
    )
    assert err is not None
    assert err.failure is not None
    assert err.failure.code == ErrorCode.WORKSPACE_BOUNDARY_VIOLATION
    assert err.failure.recoverable is False


def test_workspace_boundary_guard_allows_override(tmp_path):
    outside = tmp_path.parent / "elsewhere.py"
    err = workspace_boundary_guard(
        file=str(outside), project_root=tmp_path, allow_out_of_workspace=True,
    )
    assert err is None


def test_workspace_boundary_guard_honors_extra_paths(tmp_path, monkeypatch):
    extra = tmp_path.parent / "extra-root"
    extra.mkdir(exist_ok=True)
    target = extra / "f.py"
    target.write_text("")
    monkeypatch.setenv("O2_SCALPEL_WORKSPACE_EXTRA_PATHS", str(extra))
    err = workspace_boundary_guard(
        file=str(target), project_root=tmp_path, allow_out_of_workspace=False,
    )
    assert err is None


def test_resolve_capability_for_facade_returns_record(monkeypatch):
    fake_record = CapabilityRecord(
        id="rust.refactor.extract.function",
        language="rust",
        kind="refactor.extract.function",
        source_server="rust-analyzer",
        params_schema={},
        extension_allow_list=frozenset({".rs"}),
        preferred_facade="extract",
    )

    class _FakeCatalog:
        records = [fake_record]

    runtime = ScalpelRuntime.instance()
    monkeypatch.setattr(runtime, "catalog", lambda: _FakeCatalog())
    rec = resolve_capability_for_facade("extract", language="rust")
    assert rec is not None
    assert rec.id == "rust.refactor.extract.function"


def test_resolve_capability_for_facade_returns_none_for_unknown(monkeypatch):
    class _EmptyCatalog:
        records = []

    runtime = ScalpelRuntime.instance()
    monkeypatch.setattr(runtime, "catalog", lambda: _EmptyCatalog())
    rec = resolve_capability_for_facade("extract", language="rust")
    assert rec is None


def test_build_failure_result_shape():
    result = build_failure_result(
        code=ErrorCode.SYMBOL_NOT_FOUND,
        stage="extract",
        reason="symbol foo not found",
    )
    assert result.applied is False
    assert result.failure is not None
    assert result.failure.code == ErrorCode.SYMBOL_NOT_FOUND
    assert result.failure.stage == "extract"


def test_apply_workspace_edit_via_editor_invokes_editor():
    workspace_edit = {"changes": {}}
    fake_editor = MagicMock()
    fake_editor.apply_workspace_edit.return_value = 1
    n = apply_workspace_edit_via_editor(workspace_edit, fake_editor)
    assert n == 1
    fake_editor.apply_workspace_edit.assert_called_once_with(workspace_edit)


def test_record_checkpoint_for_workspace_edit_emits_id(monkeypatch):
    runtime = ScalpelRuntime.instance()

    class _FakeCheckpointStore:
        def __init__(self):
            self._n = 0

        def record(self, *, applied, snapshot):  # noqa: ARG002
            self._n += 1
            return f"cp_{self._n}"

    fake_store = _FakeCheckpointStore()
    monkeypatch.setattr(runtime, "checkpoint_store", lambda: fake_store)
    workspace_edit = {"changes": {}}
    snapshot = {"file:///x.py": "old"}
    cid = record_checkpoint_for_workspace_edit(workspace_edit, snapshot)
    assert isinstance(cid, str) and len(cid) > 0
    cid2 = record_checkpoint_for_workspace_edit(workspace_edit, snapshot)
    assert cid != cid2
