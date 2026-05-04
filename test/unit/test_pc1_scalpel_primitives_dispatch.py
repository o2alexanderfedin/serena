"""PC1 — unit tests for scalpel_primitives.py dispatch logic.

Covers:
- _registered_language_ids / _ensure_supported_language
- _is_in_workspace
- _run_async
- CapabilitiesListTool.apply (language filter, filter_kind)
- CapabilityDescribeTool.apply (found + unknown)
- ApplyCapabilityTool.apply (unknown capability, out-of-workspace, dispatch)
- _dispatch_via_coordinator (supports_kind gate, no-actions, dry_run, apply)
- _payload_to_step_changes, _payload_to_diagnostics_delta, _payload_to_failure
- _dry_run_one_step (unknown tool, facade exception, bad JSON, success)
- _facade_class_by_tool_name
- _translate_path_args_to_shadow
- DryRunComposeTool.apply (basic, fail_fast, all-invalid steps)
- RollbackTool.apply (no checkpoint, already reverted, real rollback)
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_primitives import (
    _dispatch_via_coordinator,
    _dry_run_one_step,
    _ensure_supported_language,
    _facade_class_by_tool_name,
    _is_in_workspace,
    _payload_to_diagnostics_delta,
    _payload_to_failure,
    _payload_to_step_changes,
    _registered_language_ids,
    _run_async,
    _translate_path_args_to_shadow,
    ApplyCapabilityTool,
    CapabilitiesListTool,
    CapabilityDescribeTool,
    DryRunComposeTool,
    RollbackTool,
)
from serena.tools.scalpel_schemas import ComposeStep, ErrorCode


# ---------------------------------------------------------------------------
# _registered_language_ids / _ensure_supported_language
# ---------------------------------------------------------------------------


def test_registered_language_ids_returns_frozenset() -> None:
    ids = _registered_language_ids()
    assert isinstance(ids, frozenset)
    # Should include at least "rust" and "python" from the default strategies.
    assert "rust" in ids
    assert "python" in ids


def test_ensure_supported_language_rust() -> None:
    result = _ensure_supported_language("rust")
    assert result == "rust"


def test_ensure_supported_language_python() -> None:
    result = _ensure_supported_language("python")
    assert result == "python"


def test_ensure_supported_language_unknown_raises() -> None:
    with pytest.raises(ValueError, match="No strategy registered"):
        _ensure_supported_language("cobol_9000")


# ---------------------------------------------------------------------------
# _is_in_workspace
# ---------------------------------------------------------------------------


def test_is_in_workspace_inside() -> None:
    root = Path("/project")
    assert _is_in_workspace("/project/src/main.rs", root) is True


def test_is_in_workspace_equals_root() -> None:
    root = Path("/project")
    assert _is_in_workspace("/project", root) is True


def test_is_in_workspace_outside() -> None:
    root = Path("/project")
    assert _is_in_workspace("/other/file.py", root) is False


def test_is_in_workspace_oserror_returns_false() -> None:
    # Trigger the OSError path by mocking Path.resolve to raise.
    from unittest.mock import patch
    with patch("pathlib.Path.resolve", side_effect=OSError("mocked error")):
        result = _is_in_workspace("/some/file.py", Path("/project"))
    assert result is False


# ---------------------------------------------------------------------------
# _run_async
# ---------------------------------------------------------------------------


def test_run_async_simple_coroutine() -> None:
    import asyncio

    async def _coro() -> int:
        return 42

    result = _run_async(_coro())
    assert result == 42


def test_run_async_with_running_loop() -> None:
    """When run inside a thread from a running loop, uses run_coroutine_threadsafe."""
    import asyncio
    import concurrent.futures

    async def _coro() -> str:
        return "hello"

    async def _runner() -> str:
        loop = asyncio.get_event_loop()
        # Submit via thread so _run_async sees a running loop.
        with concurrent.futures.ThreadPoolExecutor() as pool:
            fut = loop.run_in_executor(pool, lambda: _run_async(_coro()))
            return await asyncio.wrap_future(fut)

    result = asyncio.new_event_loop().run_until_complete(_runner())
    assert result == "hello"


# ---------------------------------------------------------------------------
# CapabilitiesListTool
# ---------------------------------------------------------------------------

def _make_mock_runtime_with_catalog(records: list) -> MagicMock:
    mock_catalog = MagicMock()
    mock_catalog.records = records
    mock_runtime = MagicMock()
    mock_runtime.catalog.return_value = mock_catalog
    return mock_runtime


def _make_mock_record(
    *,
    id: str = "rust.refactor.extract.function",
    language: str = "rust",
    kind: str = "refactor.extract.function",
    source_server: str = "rust-analyzer",
    preferred_facade: str | None = "extract",
    params_schema: dict | None = None,
    extension_allow_list: list | None = None,
) -> MagicMock:
    rec = MagicMock()
    rec.id = id
    rec.language = language
    rec.kind = kind
    rec.source_server = source_server
    rec.preferred_facade = preferred_facade
    rec.params_schema = params_schema or {}
    rec.extension_allow_list = extension_allow_list or []
    return rec


def test_capabilities_list_all_languages() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    rec = _make_mock_record()
    mock_runtime = _make_mock_runtime_with_catalog([rec])

    tool = object.__new__(CapabilitiesListTool)
    tool.get_project_root = lambda: "/tmp"  # type: ignore[method-assign]

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = tool.apply(language=None)

    payload = json.loads(result)
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["capability_id"] == "rust.refactor.extract.function"


def test_capabilities_list_language_filter() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    rust_rec = _make_mock_record(id="rust.refactor.extract.function", language="rust")
    py_rec = _make_mock_record(id="python.refactor.extract.function", language="python")
    mock_runtime = _make_mock_runtime_with_catalog([rust_rec, py_rec])

    tool = object.__new__(CapabilitiesListTool)
    tool.get_project_root = lambda: "/tmp"  # type: ignore[method-assign]

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = tool.apply(language="rust")

    payload = json.loads(result)
    assert len(payload) == 1
    assert payload[0]["language"] == "rust"


def test_capabilities_list_filter_kind() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    rec1 = _make_mock_record(id="rust.refactor.extract.function", kind="refactor.extract.function")
    rec2 = _make_mock_record(id="rust.source.organizeImports", kind="source.organizeImports")
    mock_runtime = _make_mock_runtime_with_catalog([rec1, rec2])

    tool = object.__new__(CapabilitiesListTool)
    tool.get_project_root = lambda: "/tmp"  # type: ignore[method-assign]

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = tool.apply(filter_kind="refactor.extract")

    payload = json.loads(result)
    assert len(payload) == 1
    assert "refactor.extract" in payload[0]["kind"]


def test_capabilities_list_empty_catalog() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    mock_runtime = _make_mock_runtime_with_catalog([])
    tool = object.__new__(CapabilitiesListTool)
    tool.get_project_root = lambda: "/tmp"  # type: ignore[method-assign]

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = tool.apply()

    assert json.loads(result) == []


# ---------------------------------------------------------------------------
# CapabilityDescribeTool
# ---------------------------------------------------------------------------


def test_capability_describe_found() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    rec = _make_mock_record(id="rust.refactor.extract.function")
    mock_runtime = _make_mock_runtime_with_catalog([rec])

    tool = object.__new__(CapabilityDescribeTool)
    tool.get_project_root = lambda: "/tmp"  # type: ignore[method-assign]

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = tool.apply("rust.refactor.extract.function")

    payload = json.loads(result)
    assert payload["capability_id"] == "rust.refactor.extract.function"
    assert "description" in payload


def test_capability_describe_unknown_returns_failure_payload() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    rec = _make_mock_record(id="rust.refactor.extract.function")
    mock_runtime = _make_mock_runtime_with_catalog([rec])

    tool = object.__new__(CapabilityDescribeTool)
    tool.get_project_root = lambda: "/tmp"  # type: ignore[method-assign]

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = tool.apply("completely.unknown.capability")

    payload = json.loads(result)
    assert "failure" in payload
    assert payload["failure"]["code"] == "CAPABILITY_NOT_AVAILABLE"


def test_capability_describe_unknown_no_partial_matches() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    mock_runtime = _make_mock_runtime_with_catalog([])

    tool = object.__new__(CapabilityDescribeTool)
    tool.get_project_root = lambda: "/tmp"  # type: ignore[method-assign]

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = tool.apply("nonexistent.capability.id")

    payload = json.loads(result)
    assert "failure" in payload
    assert payload["failure"]["candidates"] == []


# ---------------------------------------------------------------------------
# ApplyCapabilityTool
# ---------------------------------------------------------------------------


def test_apply_capability_unknown_capability_id() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    mock_runtime = _make_mock_runtime_with_catalog([])

    tool = object.__new__(ApplyCapabilityTool)
    tool.get_project_root = lambda: "/tmp"  # type: ignore[method-assign]

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = tool.apply(
            capability_id="unknown.capability",
            file="/tmp/foo.py",
            range_or_name_path={"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
        )

    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "CAPABILITY_NOT_AVAILABLE"


def test_apply_capability_out_of_workspace_violation(tmp_path: Path) -> None:
    import tempfile
    other = Path(tempfile.mkdtemp())
    try:
        from serena.tools.scalpel_runtime import ScalpelRuntime
        rec = _make_mock_record(id="rust.refactor.extract.function", language="rust")
        mock_runtime = _make_mock_runtime_with_catalog([rec])

        tool = object.__new__(ApplyCapabilityTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
            result = tool.apply(
                capability_id="rust.refactor.extract.function",
                file=str(other / "intruder.py"),
                range_or_name_path={"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
                allow_out_of_workspace=False,
            )

        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


def test_apply_capability_allow_out_of_workspace_passes_to_dispatch(tmp_path: Path) -> None:
    """allow_out_of_workspace=True skips boundary check and reaches dispatch."""
    from serena.tools.scalpel_runtime import ScalpelRuntime
    rec = _make_mock_record(id="rust.refactor.extract.function", language="rust")
    mock_runtime = _make_mock_runtime_with_catalog([rec])
    # Mock coordinator that returns no actions.
    mock_coord = MagicMock()
    mock_coord.supports_kind.return_value = False
    mock_runtime.coordinator_for.return_value = mock_coord

    tool = object.__new__(ApplyCapabilityTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = tool.apply(
            capability_id="rust.refactor.extract.function",
            file="/completely/outside/project.py",
            range_or_name_path={"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
            allow_out_of_workspace=True,
        )

    payload = json.loads(result)
    # Gets past boundary check; hits supports_kind gate.
    assert payload["applied"] is False


# ---------------------------------------------------------------------------
# _dispatch_via_coordinator
# ---------------------------------------------------------------------------


def _make_capability(*, language: str = "rust", kind: str = "refactor.extract.function",
                     source_server: str = "rust-analyzer") -> Any:
    cap = MagicMock()
    cap.language = language
    cap.kind = kind
    cap.source_server = source_server
    cap.id = f"{language}.refactor.extract.function"
    return cap


def test_dispatch_via_coordinator_supports_kind_gate(tmp_path: Path) -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    cap = _make_capability()
    mock_coord = MagicMock()
    mock_coord.supports_kind.return_value = False
    mock_runtime = MagicMock()
    mock_runtime.coordinator_for.return_value = mock_coord

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = _dispatch_via_coordinator(
            cap, "/tmp/foo.rs", {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
            {}, dry_run=False, preview_token=None, project_root=tmp_path,
        )

    assert result.applied is False
    assert result.failure is not None
    assert result.failure.code == ErrorCode.CAPABILITY_NOT_AVAILABLE


def test_dispatch_via_coordinator_no_actions_returns_failure(tmp_path: Path) -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    cap = _make_capability()
    mock_coord = MagicMock()
    mock_coord.supports_kind.return_value = True
    mock_coord.merge_code_actions = MagicMock(return_value=[])

    # Wrap in async coroutine for _run_async
    import asyncio

    async def _empty_actions(**kw: Any) -> list:
        return []

    mock_coord.merge_code_actions.side_effect = lambda **kw: _empty_actions(**kw)
    mock_runtime = MagicMock()
    mock_runtime.coordinator_for.return_value = mock_coord

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = _dispatch_via_coordinator(
            cap, "/tmp/foo.rs", {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
            {}, dry_run=False, preview_token=None, project_root=tmp_path,
        )

    assert result.applied is False
    assert result.failure is not None
    assert result.failure.code == ErrorCode.SYMBOL_NOT_FOUND


def test_dispatch_via_coordinator_dry_run_returns_preview_token(tmp_path: Path) -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    cap = _make_capability()
    mock_coord = MagicMock()
    mock_coord.supports_kind.return_value = True

    async def _has_action(**kw: Any) -> list:
        return [MagicMock(title="Extract Function")]

    mock_coord.merge_code_actions.side_effect = lambda **kw: _has_action(**kw)
    mock_runtime = MagicMock()
    mock_runtime.coordinator_for.return_value = mock_coord

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = _dispatch_via_coordinator(
            cap, "/tmp/foo.rs", {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
            {}, dry_run=True, preview_token=None, project_root=tmp_path,
        )

    assert result.applied is False
    assert result.no_op is False
    assert result.preview_token is not None


def test_dispatch_via_coordinator_string_range_uses_origin(tmp_path: Path) -> None:
    """When range_or_name_path is a string, the dispatcher uses (0,0)→(0,0)."""
    from serena.tools.scalpel_runtime import ScalpelRuntime
    cap = _make_capability()
    mock_coord = MagicMock()
    mock_coord.supports_kind.return_value = True

    async def _empty(**kw: Any) -> list:
        return []

    mock_coord.merge_code_actions.side_effect = lambda **kw: _empty(**kw)
    mock_runtime = MagicMock()
    mock_runtime.coordinator_for.return_value = mock_coord

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = _dispatch_via_coordinator(
            cap, "/tmp/foo.rs", "some::symbol::path",
            {}, dry_run=False, preview_token=None, project_root=tmp_path,
        )

    # Should reach the no-actions branch
    assert result.failure is not None


def test_dispatch_via_coordinator_apply_checkpoint(tmp_path: Path) -> None:
    """Successful apply returns applied=True with a checkpoint_id."""
    from serena.tools.scalpel_runtime import ScalpelRuntime
    from serena.tools.facade_support import apply_action_and_checkpoint
    cap = _make_capability()
    mock_coord = MagicMock()
    mock_coord.supports_kind.return_value = True
    mock_action = MagicMock()
    mock_action.id = "action-1"

    async def _one_action(**kw: Any) -> list:
        return [mock_action]

    mock_coord.merge_code_actions.side_effect = lambda **kw: _one_action(**kw)
    mock_runtime = MagicMock()
    mock_runtime.coordinator_for.return_value = mock_coord

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        with patch(
            "serena.tools.scalpel_primitives.apply_action_and_checkpoint",
            return_value=("ckpt-abc", {"changes": {"file:///x.py": []}}),
        ):
            result = _dispatch_via_coordinator(
                cap, "/tmp/foo.rs", {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
                {}, dry_run=False, preview_token=None, project_root=tmp_path,
            )

    assert result.applied is True
    assert result.checkpoint_id == "ckpt-abc"


def test_dispatch_via_coordinator_no_op_when_empty_checkpoint(tmp_path: Path) -> None:
    """apply_action_and_checkpoint returning empty edit → no_op=True."""
    from serena.tools.scalpel_runtime import ScalpelRuntime
    cap = _make_capability()
    mock_coord = MagicMock()
    mock_coord.supports_kind.return_value = True
    mock_action = MagicMock()
    mock_action.id = "action-1"

    async def _one_action(**kw: Any) -> list:
        return [mock_action]

    mock_coord.merge_code_actions.side_effect = lambda **kw: _one_action(**kw)
    mock_runtime = MagicMock()
    mock_runtime.coordinator_for.return_value = mock_coord

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        with patch(
            "serena.tools.scalpel_primitives.apply_action_and_checkpoint",
            return_value=("", {"changes": {}}),
        ):
            result = _dispatch_via_coordinator(
                cap, "/tmp/foo.rs", {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
                {}, dry_run=False, preview_token=None, project_root=tmp_path,
            )

    assert result.applied is False
    assert result.no_op is True


# ---------------------------------------------------------------------------
# _payload_to_step_changes, _payload_to_diagnostics_delta, _payload_to_failure
# ---------------------------------------------------------------------------


def test_payload_to_step_changes_empty_payload() -> None:
    result = _payload_to_step_changes({})
    assert result == ()


def test_payload_to_step_changes_non_list_changes() -> None:
    result = _payload_to_step_changes({"changes": "not a list"})
    assert result == ()


def test_payload_to_step_changes_drops_invalid_entries() -> None:
    payload = {"changes": [
        "not a dict",
        {"path": "/f.py", "kind": "modify", "hunks": [], "provenance": {"source": "rust-analyzer", "workspace_boundary_check": True}},
    ]}
    result = _payload_to_step_changes(payload)
    assert len(result) == 1


def test_payload_to_step_changes_all_invalid() -> None:
    payload = {"changes": ["bad1", "bad2"]}
    result = _payload_to_step_changes(payload)
    assert result == ()


def test_payload_to_diagnostics_delta_missing_key() -> None:
    result = _payload_to_diagnostics_delta({})
    assert result.before.error == 0
    assert result.after.error == 0


def test_payload_to_diagnostics_delta_non_dict_value() -> None:
    result = _payload_to_diagnostics_delta({"diagnostics_delta": "not a dict"})
    assert result.before.error == 0


def test_payload_to_diagnostics_delta_invalid_shape() -> None:
    result = _payload_to_diagnostics_delta({"diagnostics_delta": {"invalid": "shape"}})
    assert result.before.error == 0


def test_payload_to_failure_missing_key() -> None:
    result = _payload_to_failure({})
    assert result is None


def test_payload_to_failure_non_dict_value() -> None:
    result = _payload_to_failure({"failure": "not a dict"})
    assert result is None


def test_payload_to_failure_valid_failure() -> None:
    payload = {"failure": {
        "stage": "test",
        "reason": "something failed",
        "code": "SYMBOL_NOT_FOUND",
        "recoverable": True,
        "candidates": [],
    }}
    result = _payload_to_failure(payload)
    assert result is not None
    assert result.code == ErrorCode.SYMBOL_NOT_FOUND


# ---------------------------------------------------------------------------
# _dry_run_one_step
# ---------------------------------------------------------------------------


def test_dry_run_one_step_unknown_tool() -> None:
    step = ComposeStep(tool="nonexistent_tool_xyz", args={})
    with patch("serena.tools.scalpel_facades._FACADE_DISPATCH", {}):
        result = _dry_run_one_step(step, project_root=Path("/tmp"), step_index=0)

    assert result.failure is not None
    assert result.failure.code == ErrorCode.INVALID_ARGUMENT
    assert "not registered" in result.failure.reason


def test_dry_run_one_step_facade_raises_exception() -> None:
    def _bad_handler(**kw: Any) -> str:
        raise RuntimeError("handler crashed")

    step = ComposeStep(tool="bad_tool", args={})
    with patch("serena.tools.scalpel_facades._FACADE_DISPATCH", {"bad_tool": _bad_handler}):
        result = _dry_run_one_step(step, project_root=Path("/tmp"), step_index=0)

    assert result.failure is not None
    assert result.failure.code == ErrorCode.INTERNAL_ERROR
    assert "raised" in result.failure.reason


def test_dry_run_one_step_facade_returns_invalid_json() -> None:
    def _json_handler(**kw: Any) -> str:
        return "not valid json {"

    step = ComposeStep(tool="json_bad_tool", args={})
    with patch("serena.tools.scalpel_facades._FACADE_DISPATCH", {"json_bad_tool": _json_handler}):
        result = _dry_run_one_step(step, project_root=Path("/tmp"), step_index=0)

    assert result.failure is not None
    assert result.failure.code == ErrorCode.INTERNAL_ERROR
    assert "invalid JSON" in result.failure.reason


def test_dry_run_one_step_facade_returns_non_dict_json() -> None:
    def _array_handler(**kw: Any) -> str:
        return json.dumps([1, 2, 3])

    step = ComposeStep(tool="array_tool", args={})
    with patch("serena.tools.scalpel_facades._FACADE_DISPATCH", {"array_tool": _array_handler}):
        result = _dry_run_one_step(step, project_root=Path("/tmp"), step_index=0)

    assert result.failure is not None
    assert result.failure.code == ErrorCode.INTERNAL_ERROR
    assert "non-object payload" in result.failure.reason


def test_dry_run_one_step_success() -> None:
    def _good_handler(**kw: Any) -> str:
        return json.dumps({
            "applied": False,
            "no_op": False,
            "diagnostics_delta": {
                "before": {"error": 0, "warning": 0, "information": 0, "hint": 0},
                "after": {"error": 0, "warning": 0, "information": 0, "hint": 0},
                "new_findings": [],
                "severity_breakdown": {"error": 0, "warning": 0, "information": 0, "hint": 0},
            },
            "preview_token": "pv_test_123",
        })

    step = ComposeStep(tool="good_tool", args={"file": "/tmp/foo.py"})
    with patch("serena.tools.scalpel_facades._FACADE_DISPATCH", {"good_tool": _good_handler}):
        result = _dry_run_one_step(step, project_root=Path("/tmp"), step_index=2)

    assert result.step_index == 2
    assert result.tool == "good_tool"
    assert result.failure is None


def test_dry_run_one_step_passes_dry_run_true() -> None:
    """The dispatcher injects dry_run=True into args."""
    captured: dict = {}

    def _capture_handler(**kw: Any) -> str:
        captured.update(kw)
        return json.dumps({"applied": False, "diagnostics_delta": {
            "before": {"error": 0, "warning": 0, "information": 0, "hint": 0},
            "after": {"error": 0, "warning": 0, "information": 0, "hint": 0},
            "new_findings": [],
            "severity_breakdown": {"error": 0, "warning": 0, "information": 0, "hint": 0},
        }, "no_op": True})

    step = ComposeStep(tool="capture_tool", args={"file": "/tmp/x.py"})
    with patch("serena.tools.scalpel_facades._FACADE_DISPATCH", {"capture_tool": _capture_handler}):
        _dry_run_one_step(step, project_root=Path("/tmp"), step_index=0)

    assert captured.get("dry_run") is True


# ---------------------------------------------------------------------------
# _facade_class_by_tool_name
# ---------------------------------------------------------------------------


def test_facade_class_by_tool_name_extract() -> None:
    cls = _facade_class_by_tool_name("extract")
    from serena.tools.scalpel_facades import ExtractTool
    assert cls is ExtractTool


def test_facade_class_by_tool_name_legacy_prefix() -> None:
    cls = _facade_class_by_tool_name("scalpel_extract")
    from serena.tools.scalpel_facades import ExtractTool
    assert cls is ExtractTool


def test_facade_class_by_tool_name_split_file() -> None:
    cls = _facade_class_by_tool_name("split_file")
    from serena.tools.scalpel_facades import SplitFileTool
    assert cls is SplitFileTool


def test_facade_class_by_tool_name_unknown_returns_none() -> None:
    cls = _facade_class_by_tool_name("nonexistent_tool_xyz")
    assert cls is None


def test_facade_class_by_tool_name_capabilities_list() -> None:
    cls = _facade_class_by_tool_name("capabilities_list")
    assert cls is CapabilitiesListTool


# ---------------------------------------------------------------------------
# _translate_path_args_to_shadow
# ---------------------------------------------------------------------------


def test_translate_path_args_file_key_redirected(tmp_path: Path) -> None:
    live_root = tmp_path / "project"
    shadow_root = tmp_path / "shadow_project"
    live_file = str(live_root / "src" / "main.py")
    args = {"file": live_file}
    result = _translate_path_args_to_shadow(args, live_root=live_root, shadow_root=shadow_root)
    assert result["file"] == str(shadow_root / "src" / "main.py")


def test_translate_path_args_files_list_redirected(tmp_path: Path) -> None:
    live_root = tmp_path / "project"
    shadow_root = tmp_path / "shadow_project"
    live_file = str(live_root / "foo.py")
    args = {"files": [live_file, "/outside/project/bar.py"]}
    result = _translate_path_args_to_shadow(args, live_root=live_root, shadow_root=shadow_root)
    redirected = result["files"]
    assert redirected[0] == str(shadow_root / "foo.py")
    assert redirected[1] == "/outside/project/bar.py"  # outside live_root — unchanged


def test_translate_path_args_non_path_keys_pass_through(tmp_path: Path) -> None:
    live_root = tmp_path / "project"
    shadow_root = tmp_path / "shadow"
    args = {"language": "rust", "dry_run": False, "groups": {"target": ["foo"]}}
    result = _translate_path_args_to_shadow(args, live_root=live_root, shadow_root=shadow_root)
    assert result == args


def test_translate_path_args_file_outside_live_root_unchanged(tmp_path: Path) -> None:
    live_root = tmp_path / "project"
    shadow_root = tmp_path / "shadow"
    args = {"file": "/completely/outside/file.py"}
    result = _translate_path_args_to_shadow(args, live_root=live_root, shadow_root=shadow_root)
    assert result["file"] == "/completely/outside/file.py"


# ---------------------------------------------------------------------------
# DryRunComposeTool
# ---------------------------------------------------------------------------


def _make_dry_run_tool(project_root: str = "/tmp") -> DryRunComposeTool:
    tool = object.__new__(DryRunComposeTool)
    tool.get_project_root = lambda: project_root  # type: ignore[method-assign]
    return tool


def test_dry_run_compose_all_invalid_steps() -> None:
    """All malformed steps → empty per_step with warnings, but still returns ComposeResult."""
    from serena.tools.scalpel_runtime import ScalpelRuntime
    mock_txn = MagicMock()
    mock_txn.begin.return_value = "raw-id-1"
    mock_runtime = MagicMock()
    mock_runtime.transaction_store.return_value = mock_txn
    mock_runtime.checkpoint_store.return_value = MagicMock()

    tool = _make_dry_run_tool()

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = tool.apply(
            steps=[{"bad_key": "missing_tool_key"}],
            fail_fast=True,
        )

    payload = json.loads(result)
    assert "transaction_id" in payload
    assert len(payload["warnings"]) > 0


def test_dry_run_compose_basic_valid_step() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    mock_txn_store = MagicMock()
    mock_txn_store.begin.return_value = "txn-raw-1"
    mock_txn_store.add_step = MagicMock()
    mock_txn_store.set_expires_at = MagicMock()
    mock_runtime = MagicMock()
    mock_runtime.transaction_store.return_value = mock_txn_store

    tool = _make_dry_run_tool()

    def _good_handler(**kw: Any) -> str:
        return json.dumps({"applied": False, "no_op": True, "diagnostics_delta": {
            "before": {"error": 0, "warning": 0, "information": 0, "hint": 0},
            "after": {"error": 0, "warning": 0, "information": 0, "hint": 0},
            "new_findings": [],
            "severity_breakdown": {"error": 0, "warning": 0, "information": 0, "hint": 0},
        }})

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        with patch("serena.tools.scalpel_facades._FACADE_DISPATCH", {"good_tool": _good_handler}):
            result = tool.apply(
                steps=[{"tool": "good_tool", "args": {"file": "/tmp/foo.py"}}],
                fail_fast=True,
            )

    payload = json.loads(result)
    assert "transaction_id" in payload
    assert payload["transaction_id"].startswith("txn_")
    assert len(payload["per_step"]) == 1


def test_dry_run_compose_fail_fast_stops_at_first_failure() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    mock_txn_store = MagicMock()
    mock_txn_store.begin.return_value = "txn-raw-2"
    mock_txn_store.add_step = MagicMock()
    mock_txn_store.set_expires_at = MagicMock()
    mock_runtime = MagicMock()
    mock_runtime.transaction_store.return_value = mock_txn_store

    tool = _make_dry_run_tool()
    call_count = [0]

    def _failing_handler(**kw: Any) -> str:
        call_count[0] += 1
        return json.dumps({"applied": False, "no_op": False, "diagnostics_delta": {
            "before": {"error": 0, "warning": 0, "information": 0, "hint": 0},
            "after": {"error": 0, "warning": 0, "information": 0, "hint": 0},
            "new_findings": [],
            "severity_breakdown": {"error": 0, "warning": 0, "information": 0, "hint": 0},
        }, "failure": {
            "stage": "s", "reason": "forced failure", "code": "SYMBOL_NOT_FOUND",
            "recoverable": True, "candidates": [],
        }})

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        with patch("serena.tools.scalpel_facades._FACADE_DISPATCH", {"fail_tool": _failing_handler}):
            result = tool.apply(
                steps=[
                    {"tool": "fail_tool", "args": {}},
                    {"tool": "fail_tool", "args": {}},
                    {"tool": "fail_tool", "args": {}},
                ],
                fail_fast=True,
            )

    payload = json.loads(result)
    # fail_fast=True: only 1 step executed, 2 skipped
    assert len(payload["per_step"]) == 1
    assert "TRANSACTION_ABORTED" in " ".join(payload["warnings"])


def test_dry_run_compose_no_fail_fast_runs_all_steps() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    mock_txn_store = MagicMock()
    mock_txn_store.begin.return_value = "txn-raw-3"
    mock_txn_store.add_step = MagicMock()
    mock_txn_store.set_expires_at = MagicMock()
    mock_runtime = MagicMock()
    mock_runtime.transaction_store.return_value = mock_txn_store

    tool = _make_dry_run_tool()

    def _any_handler(**kw: Any) -> str:
        return json.dumps({"applied": False, "no_op": True, "diagnostics_delta": {
            "before": {"error": 0, "warning": 0, "information": 0, "hint": 0},
            "after": {"error": 0, "warning": 0, "information": 0, "hint": 0},
            "new_findings": [],
            "severity_breakdown": {"error": 0, "warning": 0, "information": 0, "hint": 0},
        }})

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        with patch("serena.tools.scalpel_facades._FACADE_DISPATCH", {"any_tool": _any_handler}):
            result = tool.apply(
                steps=[
                    {"tool": "any_tool", "args": {}},
                    {"tool": "any_tool", "args": {}},
                ],
                fail_fast=False,
            )

    payload = json.loads(result)
    assert len(payload["per_step"]) == 2


# ---------------------------------------------------------------------------
# RollbackTool
# ---------------------------------------------------------------------------


def _make_rollback_tool() -> RollbackTool:
    tool = object.__new__(RollbackTool)
    tool.get_project_root = lambda: "/tmp"  # type: ignore[method-assign]
    return tool


def test_rollback_tool_unknown_checkpoint_returns_no_op() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    mock_store = MagicMock()
    mock_store.get.return_value = None
    mock_runtime = MagicMock()
    mock_runtime.checkpoint_store.return_value = mock_store

    tool = _make_rollback_tool()

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = tool.apply("unknown-checkpoint-id")

    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["no_op"] is True


def test_rollback_tool_already_reverted_is_idempotent() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    mock_ckpt = MagicMock()
    mock_ckpt.reverted = True
    mock_store = MagicMock()
    mock_store.get.return_value = mock_ckpt
    mock_runtime = MagicMock()
    mock_runtime.checkpoint_store.return_value = mock_store

    tool = _make_rollback_tool()

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = tool.apply("already-reverted-id")

    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["no_op"] is True


def test_rollback_tool_calls_inverse_apply(tmp_path: Path) -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    from serena.tools.facade_support import inverse_apply_checkpoint
    mock_ckpt = MagicMock()
    mock_ckpt.reverted = False
    mock_store = MagicMock()
    mock_store.get.return_value = mock_ckpt
    mock_runtime = MagicMock()
    mock_runtime.checkpoint_store.return_value = mock_store

    tool = _make_rollback_tool()

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        with patch(
            "serena.tools.scalpel_primitives.inverse_apply_checkpoint",
            return_value=(True, []),
        ) as mock_inv:
            result = tool.apply("valid-checkpoint-id")

    mock_inv.assert_called_once_with("valid-checkpoint-id")
    payload = json.loads(result)
    assert payload["applied"] is True
    assert mock_ckpt.reverted is True


def test_rollback_tool_inverse_apply_fails_no_op(tmp_path: Path) -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    mock_ckpt = MagicMock()
    mock_ckpt.reverted = False
    mock_store = MagicMock()
    mock_store.get.return_value = mock_ckpt
    mock_runtime = MagicMock()
    mock_runtime.checkpoint_store.return_value = mock_store

    tool = _make_rollback_tool()

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        with patch(
            "serena.tools.scalpel_primitives.inverse_apply_checkpoint",
            return_value=(False, ["something failed"]),
        ):
            result = tool.apply("ckpt-fail")

    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["no_op"] is True
    # reverted flag NOT flipped since ok=False
    assert mock_ckpt.reverted is False
