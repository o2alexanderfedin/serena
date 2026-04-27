"""v1.1 Stream 5 / Leaf 02 — Task 4: settings/factory wiring.

Verifies:

1. ``default_checkpoint_disk_root()`` resolves to ``${O2_SCALPEL_CACHE}/checkpoints``
   when the env var is set.
2. Without the env var, it resolves under ``platformdirs.user_cache_dir`` —
   matching the spec's ``${O2_SCALPEL_CACHE}/checkpoints/`` semantics.
3. The production ``ScalpelRuntime.checkpoint_store()`` factory ALWAYS
   supplies a non-None ``disk_root`` — the S3 critic guard from spec
   line 174-178. Bypassing it via ``CheckpointStore()`` is the test-only
   override.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from serena.refactoring.checkpoint_default_root import (
    O2_SCALPEL_CACHE_ENV,
    default_checkpoint_disk_root,
)
from serena.refactoring.checkpoints import CheckpointStore
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def _reset_runtime() -> None:
    ScalpelRuntime.reset_for_testing()


def test_default_root_uses_o2_scalpel_cache_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(O2_SCALPEL_CACHE_ENV, str(tmp_path))
    root = default_checkpoint_disk_root()
    assert root == tmp_path / "checkpoints"


def test_default_root_falls_back_to_platformdirs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(O2_SCALPEL_CACHE_ENV, raising=False)
    root = default_checkpoint_disk_root()
    # Must resolve to something containing 'o2-scalpel' and end in 'checkpoints'.
    assert root.name == "checkpoints"
    assert "o2-scalpel" in str(root)


def test_default_root_strips_blank_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty/whitespace env var must NOT short-circuit the platformdirs default."""
    monkeypatch.setenv(O2_SCALPEL_CACHE_ENV, "   ")
    root = default_checkpoint_disk_root()
    assert root.name == "checkpoints"
    assert "o2-scalpel" in str(root)


def test_default_root_returns_absolute_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(O2_SCALPEL_CACHE_ENV, raising=False)
    root = default_checkpoint_disk_root()
    assert root.is_absolute()


def test_production_factory_always_supplies_disk_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3 critic guard: production factory MUST pass a disk_root through.

    We pin O2_SCALPEL_CACHE to a tmp_path so the test does not write into
    the user's real platformdirs cache. The factory must build a store
    whose ``_disk`` is a live ``DiskCheckpointStore`` rooted under that
    path."""
    monkeypatch.setenv(O2_SCALPEL_CACHE_ENV, str(tmp_path))
    runtime = ScalpelRuntime.instance()
    store = runtime.checkpoint_store()
    # S3 guard.
    assert store._disk is not None  # type: ignore[attr-defined]
    # Rooted under our tmp_path/checkpoints (or a subdirectory of it).
    expected_root = (tmp_path / "checkpoints").resolve()
    actual_root = store._disk.root.resolve()  # type: ignore[attr-defined]
    assert actual_root == expected_root


def test_factory_singleton_returns_same_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(O2_SCALPEL_CACHE_ENV, str(tmp_path))
    runtime = ScalpelRuntime.instance()
    s1 = runtime.checkpoint_store()
    s2 = runtime.checkpoint_store()
    assert s1 is s2


def test_factory_built_store_persists_across_recreation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end smoke: factory-built store + restart preserves checkpoints."""
    monkeypatch.setenv(O2_SCALPEL_CACHE_ENV, str(tmp_path))
    runtime = ScalpelRuntime.instance()
    store = runtime.checkpoint_store()
    cid = store.record(
        applied={
            "documentChanges": [
                {
                    "textDocument": {"uri": "file:///x.py", "version": 1},
                    "edits": [
                        {
                            "range": {
                                "start": {"line": 0, "character": 0},
                                "end": {"line": 0, "character": 0},
                            },
                            "newText": "x=1\n",
                        }
                    ],
                }
            ]
        },
        snapshot={"file:///x.py": "old\n"},
    )
    # Simulate process restart.
    ScalpelRuntime.reset_for_testing()
    runtime2 = ScalpelRuntime.instance()
    store2 = runtime2.checkpoint_store()
    # Different CheckpointStore instance, same disk_root.
    assert store2 is not store
    got = store2.get(cid)
    assert got is not None
    assert got.id == cid


def test_test_only_override_bypasses_disk() -> None:
    """``CheckpointStore()`` no-arg form remains valid for tests (S3 carve-out)."""
    s = CheckpointStore()
    assert s._disk is None  # type: ignore[attr-defined]
