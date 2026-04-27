"""v1.1 Stream 5 / Leaf 07 Task 3 — `scalpel_convert_from_relative_imports` tests.

Drives rope's ``ImportTools.relatives_to_absolutes`` through the facade.
Three branches per spec R3:

1. ``from .x import y`` -> ``from pkg.x import y`` (sibling-symbol form,
   happy path, Step 3.1).
2. ``from ..x import y`` -> ``from pkg.x import y`` (parent-relative
   form, Step 3.4).
3. ``from . import x`` -> ``from pkg import x`` (module-import form,
   Step 3.5 — distinct rope AST branch per the critic R3 note).

Plus auto-registration / naming + a no-op (already-absolute) skip path.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from serena.tools.scalpel_facades import ScalpelConvertFromRelativeImportsTool
from serena.tools.scalpel_runtime import ScalpelRuntime
from serena.tools.tools_base import Tool
from serena.util.inspection import iter_subclasses


@pytest.fixture(autouse=True)
def _reset_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    monkeypatch.setenv("O2_SCALPEL_CACHE", str(tmp_path / "cache"))
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def _build_tool(tmp_path: Path) -> ScalpelConvertFromRelativeImportsTool:
    agent = MagicMock(name="SerenaAgent")
    agent.get_project_root.return_value = str(tmp_path)
    tool = ScalpelConvertFromRelativeImportsTool(agent=agent)
    object.__setattr__(tool, "get_project_root", lambda: str(tmp_path))
    return tool


# ---------------------------------------------------------------------------
# Step 3.1 — happy path: `from .x import y`
# ---------------------------------------------------------------------------


def test_convert_from_relative_imports_uses_rope_relatives_to_absolutes(
    tmp_path: Path,
) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "x.py").write_text("VAL = 1\n", encoding="utf-8")
    (tmp_path / "pkg" / "y.py").write_text(
        "from .x import VAL\n", encoding="utf-8",
    )
    tool = _build_tool(tmp_path)

    payload = json.loads(
        tool.apply(file="pkg/y.py", allow_out_of_workspace=True),
    )
    assert payload["applied"] is True
    assert (
        (tmp_path / "pkg" / "y.py").read_text(encoding="utf-8")
        == "from pkg.x import VAL\n"
    )


# ---------------------------------------------------------------------------
# Step 3.4 — parent-relative form: `from ..x import y`
# ---------------------------------------------------------------------------


def test_convert_from_relative_imports_resolves_parent_relative(
    tmp_path: Path,
) -> None:
    (tmp_path / "pkg" / "sub").mkdir(parents=True)
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "sub" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "x.py").write_text("VAL = 2\n", encoding="utf-8")
    (tmp_path / "pkg" / "sub" / "y.py").write_text(
        "from ..x import VAL\n", encoding="utf-8",
    )
    tool = _build_tool(tmp_path)

    payload = json.loads(
        tool.apply(file="pkg/sub/y.py", allow_out_of_workspace=True),
    )
    assert payload["applied"] is True
    assert (
        (tmp_path / "pkg" / "sub" / "y.py").read_text(encoding="utf-8")
        == "from pkg.x import VAL\n"
    )


# ---------------------------------------------------------------------------
# Step 3.5 — module-import form: `from . import x`
# ---------------------------------------------------------------------------


def test_convert_from_relative_imports_handles_module_import_form(
    tmp_path: Path,
) -> None:
    """Module-import form binds ``x`` as a module object — distinct rope
    AST branch from the sibling-symbol form per critic R3 in the spec."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "x.py").write_text("VAL = 3\n", encoding="utf-8")
    (tmp_path / "pkg" / "y.py").write_text(
        "from . import x\n\nUSE = x.VAL\n", encoding="utf-8",
    )
    tool = _build_tool(tmp_path)

    payload = json.loads(
        tool.apply(file="pkg/y.py", allow_out_of_workspace=True),
    )
    assert payload["applied"] is True
    assert (
        (tmp_path / "pkg" / "y.py").read_text(encoding="utf-8")
        == "from pkg import x\n\nUSE = x.VAL\n"
    )


# ---------------------------------------------------------------------------
# No-op when the module already uses only absolute imports
# ---------------------------------------------------------------------------


def test_convert_from_relative_imports_skips_when_already_absolute(
    tmp_path: Path,
) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "x.py").write_text("VAL = 4\n", encoding="utf-8")
    src = "from pkg.x import VAL\n"
    (tmp_path / "pkg" / "y.py").write_text(src, encoding="utf-8")
    tool = _build_tool(tmp_path)

    payload = json.loads(
        tool.apply(file="pkg/y.py", allow_out_of_workspace=True),
    )
    assert payload["applied"] is False
    assert payload["no_op"] is True
    assert payload["language_options"]["reason"] == "no_relative_imports"
    assert (tmp_path / "pkg" / "y.py").read_text(encoding="utf-8") == src


# ---------------------------------------------------------------------------
# Auto-registration / naming
# ---------------------------------------------------------------------------


def test_convert_from_relative_imports_tool_appears_in_iter_subclasses() -> None:
    discovered = {cls.get_name_from_cls() for cls in iter_subclasses(Tool)}
    assert "scalpel_convert_from_relative_imports" in discovered


def test_convert_from_relative_imports_tool_class_name_is_snake_cased() -> None:
    assert (
        ScalpelConvertFromRelativeImportsTool.get_name_from_cls()
        == "scalpel_convert_from_relative_imports"
    )
