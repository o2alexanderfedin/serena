"""Tests for :func:`serena.marketplace.build.resolve_engine_sha`.

Covers three scenarios:

1. **gitdir-pointer** (submodule checkout): ``<sub>/.git`` is a plain file
   containing ``gitdir: <relative_path>`` pointing at the real git dir inside
   the parent's ``.git/modules/<sub>/``.  The function must follow the pointer
   and return the SUBMODULE SHA, NOT the parent repo SHA.

2. **real .git directory** (standalone / non-submodule checkout): ``.git`` is
   a directory; HEAD ref is resolved directly.

3. **no .git anywhere** in the ancestor chain: the function must return
   ``"unknown"`` gracefully.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import serena.marketplace.build as _build_mod
from serena.marketplace.build import resolve_engine_sha


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_head_via_ref(gitdir: Path, sha: str, branch: str = "main") -> None:
    """Write HEAD → refs/heads/<branch> → sha inside *gitdir*."""
    head = gitdir / "HEAD"
    head.write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")
    ref_path = gitdir / "refs" / "heads" / branch
    ref_path.parent.mkdir(parents=True, exist_ok=True)
    ref_path.write_text(sha + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. gitdir-pointer case  (THE BUG FIX TARGET)
# ---------------------------------------------------------------------------


def test_resolve_engine_sha_follows_gitdir_pointer_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When .git is a pointer file (submodule case), resolve through it
    instead of walking past to find the parent repo's .git directory."""

    # Layout:
    #   tmp_path/parent/.git/HEAD                              → "ref: refs/heads/main"
    #   tmp_path/parent/.git/refs/heads/main                   → "PARENT_SHA..."
    #   tmp_path/parent/.git/modules/sub/HEAD                  → "ref: refs/heads/main"
    #   tmp_path/parent/.git/modules/sub/refs/heads/main       → "SUBMODULE_SHA..."
    #   tmp_path/parent/sub/.git                               → "gitdir: ../.git/modules/sub"
    #   (fake module source path inside tmp_path/parent/sub/)

    parent_repo = tmp_path / "parent"
    parent_gitdir = parent_repo / ".git"
    submod_gitdir = parent_gitdir / "modules" / "sub"

    parent_gitdir.mkdir(parents=True)
    submod_gitdir.mkdir(parents=True)

    parent_sha = "a" * 40
    submodule_sha = "b" * 40

    _write_head_via_ref(parent_gitdir, parent_sha)
    _write_head_via_ref(submod_gitdir, submodule_sha)

    # Submodule .git pointer file
    sub_root = parent_repo / "sub"
    fake_module_dir = sub_root / "src" / "serena" / "marketplace"
    fake_module_dir.mkdir(parents=True)
    (sub_root / ".git").write_text(
        "gitdir: ../.git/modules/sub\n", encoding="utf-8"
    )

    # Patch __file__ so resolve_engine_sha thinks it lives inside the submodule
    fake_module_file = str(fake_module_dir / "build.py")
    monkeypatch.setattr(_build_mod, "__file__", fake_module_file)

    sha = resolve_engine_sha()
    assert sha == submodule_sha, (
        f"Expected submodule SHA {submodule_sha!r}, got {sha!r}. "
        "The function is likely reading the parent repo's HEAD."
    )


# ---------------------------------------------------------------------------
# 2. normal .git directory case
# ---------------------------------------------------------------------------


def test_resolve_engine_sha_normal_git_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-submodule case: .git is a real directory, HEAD ref resolved directly."""

    gitdir = tmp_path / ".git"
    gitdir.mkdir()
    expected_sha = "c" * 40
    _write_head_via_ref(gitdir, expected_sha)

    fake_module_file = str(tmp_path / "src" / "serena" / "marketplace" / "build.py")
    monkeypatch.setattr(_build_mod, "__file__", fake_module_file)

    sha = resolve_engine_sha()
    assert sha == expected_sha


def test_resolve_engine_sha_detached_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Detached HEAD: HEAD contains a raw SHA, not a ref: symbolic ref."""

    gitdir = tmp_path / ".git"
    gitdir.mkdir()
    expected_sha = "d" * 40
    (gitdir / "HEAD").write_text(expected_sha + "\n", encoding="utf-8")

    fake_module_file = str(tmp_path / "src" / "build.py")
    monkeypatch.setattr(_build_mod, "__file__", fake_module_file)

    sha = resolve_engine_sha()
    assert sha == expected_sha


# ---------------------------------------------------------------------------
# 3. no .git anywhere
# ---------------------------------------------------------------------------


def test_resolve_engine_sha_falls_back_to_unknown_when_no_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No .git anywhere up the tree → 'unknown' (existing behaviour preserved)."""

    # Place the fake module inside tmp_path; no .git created anywhere
    fake_module_file = str(tmp_path / "src" / "marketplace" / "build.py")
    monkeypatch.setattr(_build_mod, "__file__", fake_module_file)

    sha = resolve_engine_sha()
    assert sha == "unknown"


# ---------------------------------------------------------------------------
# 4. gitdir pointer — malformed content
# ---------------------------------------------------------------------------


def test_resolve_engine_sha_malformed_gitdir_pointer_returns_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the .git pointer file doesn't start with 'gitdir: ', return 'unknown'."""

    sub_root = tmp_path / "sub"
    sub_root.mkdir()
    (sub_root / ".git").write_text("NOT_A_GITDIR_POINTER\n", encoding="utf-8")

    fake_module_file = str(sub_root / "src" / "build.py")
    monkeypatch.setattr(_build_mod, "__file__", fake_module_file)

    sha = resolve_engine_sha()
    assert sha == "unknown"


# ---------------------------------------------------------------------------
# 5. gitdir pointer — pointer target does not exist
# ---------------------------------------------------------------------------


def test_resolve_engine_sha_broken_gitdir_target_returns_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pointer file exists but the target directory doesn't → 'unknown'."""

    sub_root = tmp_path / "sub"
    sub_root.mkdir()
    # Points to a directory that doesn't exist
    (sub_root / ".git").write_text(
        "gitdir: ../nonexistent/.git/modules/sub\n", encoding="utf-8"
    )

    fake_module_file = str(sub_root / "src" / "build.py")
    monkeypatch.setattr(_build_mod, "__file__", fake_module_file)

    sha = resolve_engine_sha()
    assert sha == "unknown"
