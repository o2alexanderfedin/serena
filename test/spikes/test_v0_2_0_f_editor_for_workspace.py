"""v0.2.0-F — ScalpelRuntime.editor_for_workspace exposed publicly.

Backlog item #7 from MVP cut. Returns a typed ``WorkspaceEditor`` handle
that wraps the per-(language, project_root) ``MultiServerCoordinator`` plus
the workspace-boundary helper. External callers (Stage 2A facades, LLM
tools, future Stage 3 facades) can ask the runtime for an editor instead of
threading the coordinator + boundary check through call sites.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from serena.tools.scalpel_runtime import (
    ScalpelRuntime,
    WorkspaceEditor,
    _AsyncAdapter,
)


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def _stub_strategy_registry():
    """Return a STRATEGY_REGISTRY-compatible stub that doesn't spawn LSPs."""
    from solidlsp.ls_config import Language

    class _StubServer:
        pass

    class _StubStrategy:
        # Catalog walk (post-DLp2) reads these as ClassVars; provide an
        # empty allow-list so the stub doesn't add records to the catalog
        # (and so build_capability_catalog can complete).
        language_id = "rust"
        code_action_allow_list: frozenset[str] = frozenset()
        extension_allow_list: frozenset[str] = frozenset({".rs"})

        def __init__(self, pool):
            self._pool = pool

        def build_servers(self, project_root):
            del project_root
            return {"stub": _AsyncAdapter(_StubServer())}

    return {Language.RUST: _StubStrategy}


def test_editor_for_workspace_returns_workspace_editor(tmp_path: Path):
    from solidlsp.ls_config import Language
    project_root = tmp_path / "myproject"
    project_root.mkdir()
    runtime = ScalpelRuntime.instance()
    with patch(
        "serena.tools.scalpel_runtime.STRATEGY_REGISTRY",
        _stub_strategy_registry(),
    ):
        editor = runtime.editor_for_workspace(Language.RUST, project_root)
    assert isinstance(editor, WorkspaceEditor)
    assert editor.project_root == project_root.resolve()


def test_editor_reuses_coordinator_on_repeat_call(tmp_path: Path):
    from solidlsp.ls_config import Language
    project_root = tmp_path / "myproject"
    project_root.mkdir()
    runtime = ScalpelRuntime.instance()
    with patch(
        "serena.tools.scalpel_runtime.STRATEGY_REGISTRY",
        _stub_strategy_registry(),
    ):
        e1 = runtime.editor_for_workspace(Language.RUST, project_root)
        e2 = runtime.editor_for_workspace(Language.RUST, project_root)
    assert e1.coordinator is e2.coordinator


def test_workspace_editor_is_in_workspace_admits_paths_under_root(
    tmp_path: Path,
):
    from solidlsp.ls_config import Language
    project_root = tmp_path / "myproject"
    project_root.mkdir()
    (project_root / "src").mkdir()
    runtime = ScalpelRuntime.instance()
    with patch(
        "serena.tools.scalpel_runtime.STRATEGY_REGISTRY",
        _stub_strategy_registry(),
    ):
        editor = runtime.editor_for_workspace(Language.RUST, project_root)
    nested = project_root / "src" / "deeper" / "x.rs"
    assert editor.is_in_workspace(nested)


def test_workspace_editor_is_in_workspace_rejects_outside_root(
    tmp_path: Path,
):
    from solidlsp.ls_config import Language
    project_root = tmp_path / "myproject"
    project_root.mkdir()
    runtime = ScalpelRuntime.instance()
    with patch(
        "serena.tools.scalpel_runtime.STRATEGY_REGISTRY",
        _stub_strategy_registry(),
    ):
        editor = runtime.editor_for_workspace(Language.RUST, project_root)
    out = tmp_path / "registry" / "fakelib" / "src" / "lib.rs"
    assert not editor.is_in_workspace(out)


def test_workspace_editor_is_in_workspace_admits_via_extra_paths_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    from solidlsp.ls_config import Language
    project_root = tmp_path / "myproject"
    project_root.mkdir()
    vendored = tmp_path / "vendor"
    vendored.mkdir()
    monkeypatch.setenv("O2_SCALPEL_WORKSPACE_EXTRA_PATHS", str(vendored))
    runtime = ScalpelRuntime.instance()
    with patch(
        "serena.tools.scalpel_runtime.STRATEGY_REGISTRY",
        _stub_strategy_registry(),
    ):
        editor = runtime.editor_for_workspace(Language.RUST, project_root)
    target = vendored / "fakelib" / "src" / "lib.rs"
    assert editor.is_in_workspace(target)


def test_workspace_editor_canonicalises_project_root(tmp_path: Path):
    """Trailing slash, ../, and ~ are normalised on construction."""
    from solidlsp.ls_config import Language
    project_root = tmp_path / "myproject"
    project_root.mkdir()
    nested = tmp_path / "myproject" / ".." / "myproject"
    runtime = ScalpelRuntime.instance()
    with patch(
        "serena.tools.scalpel_runtime.STRATEGY_REGISTRY",
        _stub_strategy_registry(),
    ):
        editor = runtime.editor_for_workspace(Language.RUST, nested)
    assert editor.project_root == project_root.resolve()
