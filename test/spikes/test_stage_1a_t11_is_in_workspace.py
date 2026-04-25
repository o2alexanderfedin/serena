"""T11 — is_in_workspace path filter (Q4 §7.1; Phase 0 P-WB cases).

Five test cases mirror P-WB's matrix:
1. In-workspace target.
2. Outside-workspace target.
3. extra_paths opt-in includes a sibling root.
4. Symlink resolves to outside (target is symlink under root, real file elsewhere).
5. Cargo registry path simulated as outside default.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from solidlsp.ls import SolidLanguageServer


def test_in_workspace(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "src").mkdir()
    f = root / "src" / "main.py"
    f.write_text("")
    assert SolidLanguageServer.is_in_workspace(str(f), [str(root)]) is True


def test_outside_workspace(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    other = tmp_path / "outside.py"
    other.write_text("")
    assert SolidLanguageServer.is_in_workspace(str(other), [str(root)]) is False


def test_extra_paths_opts_in(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    other_root = tmp_path / "registry"
    other_root.mkdir()
    f = other_root / "lib.py"
    f.write_text("")
    assert SolidLanguageServer.is_in_workspace(str(f), [str(root)]) is False
    assert SolidLanguageServer.is_in_workspace(str(f), [str(root)], extra_paths=[str(other_root)]) is True


def test_symlink_resolves_to_outside(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    real = tmp_path / "real"
    real.mkdir()
    f_real = real / "main.py"
    f_real.write_text("")
    link = root / "link.py"
    try:
        os.symlink(f_real, link)
    except (OSError, NotImplementedError):
        pytest.skip("platform without symlink support")
    # Resolve both sides (Path.resolve()): symlink target lives outside `root`.
    assert SolidLanguageServer.is_in_workspace(str(link), [str(root)]) is False


def test_registry_path_outside_default(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    registry = tmp_path / ".cargo" / "registry" / "src" / "index.crates.io" / "serde-1.0" / "lib.rs"
    registry.parent.mkdir(parents=True)
    registry.write_text("")
    assert SolidLanguageServer.is_in_workspace(str(registry), [str(root)]) is False


def test_handles_nonexistent_target_gracefully(tmp_path: Path) -> None:
    """Path.resolve() on a non-existent path still resolves the prefix; should not raise."""
    root = tmp_path / "proj"
    root.mkdir()
    nonexistent = root / "deep" / "nested" / "ghost.py"
    # Don't create the file. Resolve should still work.
    assert SolidLanguageServer.is_in_workspace(str(nonexistent), [str(root)]) is True


def test_handles_nonexistent_root_gracefully(tmp_path: Path) -> None:
    """If a root doesn't exist, that root is silently skipped."""
    real_root = tmp_path / "proj"
    real_root.mkdir()
    f = real_root / "main.py"
    f.write_text("")
    # Pass one bogus root + one real root; should still find the file under the real root.
    assert SolidLanguageServer.is_in_workspace(str(f), ["/no/such/dir/anywhere", str(real_root)]) is True
