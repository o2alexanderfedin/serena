"""T1 — LspPoolKey frozen dataclass: canonicalisation + equality + hashability."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from serena.refactoring.lsp_pool import LspPoolKey


def test_construction_canonicalises_relative_to_absolute(tmp_path: Path) -> None:
    rel = os.path.relpath(tmp_path, start=os.getcwd())
    key_rel = LspPoolKey(language="rust", project_root=rel)
    key_abs = LspPoolKey(language="rust", project_root=str(tmp_path))
    assert key_rel == key_abs
    assert hash(key_rel) == hash(key_abs)


def test_construction_strips_trailing_slash(tmp_path: Path) -> None:
    a = LspPoolKey(language="rust", project_root=str(tmp_path))
    b = LspPoolKey(language="rust", project_root=str(tmp_path) + "/")
    assert a == b


def test_resolved_path_is_pathlib_Path() -> None:
    key = LspPoolKey(language="python", project_root="/tmp")
    assert isinstance(key.project_root_path, Path)
    assert key.project_root_path.is_absolute()


def test_distinct_languages_distinct_keys(tmp_path: Path) -> None:
    a = LspPoolKey(language="rust", project_root=str(tmp_path))
    b = LspPoolKey(language="python", project_root=str(tmp_path))
    assert a != b
    assert hash(a) != hash(b)


def test_key_is_hashable_and_usable_in_dict(tmp_path: Path) -> None:
    a = LspPoolKey(language="rust", project_root=str(tmp_path))
    d: dict[LspPoolKey, int] = {a: 1}
    assert d[LspPoolKey(language="rust", project_root=str(tmp_path))] == 1


def test_key_is_immutable() -> None:
    key = LspPoolKey(language="rust", project_root="/tmp")
    with pytest.raises(Exception):
        key.language = "python"  # type: ignore[misc]


def test_symlink_resolution(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    a = LspPoolKey(language="rust", project_root=str(real))
    b = LspPoolKey(language="rust", project_root=str(link))
    assert a == b
