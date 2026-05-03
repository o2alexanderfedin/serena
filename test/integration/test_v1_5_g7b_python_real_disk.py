"""v1.5 G7-B — real-disk acid tests for 10 Python ergonomic facades.

Spec § Test discipline gaps (lines 157-174). Mirror image of G7-A
for the Python-arm half of the 21 zero-coverage facades.

Discipline (same as G7-A):
  * one test per facade (10 total).
  * each test sets ``before = src.read_text()`` *before* the call.
  * each test asserts ``after != before`` and a substring of the
    expected new content.
  * tests use a mocked coordinator so they're fast + deterministic;
    they prove the dispatcher → applier → disk path is honest
    end-to-end without requiring pylsp / ruff / basedpyright on PATH.

Facades covered (10):
  1. InlineTool
  2. ImportsOrganizeTool
  3. ConvertToMethodObjectTool
  4. LocalToFieldTool
  5. UseFunctionTool
  6. IntroduceParameterTool
  7. GenerateFromUndefinedTool
  8. AutoImportSpecializedTool
  9. FixLintsTool
  10. IgnoreDiagnosticTool

Authored-by: AI Hive®.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import (
    AutoImportSpecializedTool,
    ConvertToMethodObjectTool,
    FixLintsTool,
    GenerateFromUndefinedTool,
    IgnoreDiagnosticTool,
    ImportsOrganizeTool,
    InlineTool,
    IntroduceParameterTool,
    LocalToFieldTool,
    UseFunctionTool,
)
from serena.tools.scalpel_runtime import ScalpelRuntime


# ---------------------------------------------------------------------------
# Shared fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


_T = TypeVar("_T")


def _make_tool(cls: type[_T], project_root: Path) -> _T:
    tool = cls.__new__(cls)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[attr-defined]
    return tool


def _action(action_id: str, title: str, kind: str) -> MagicMock:
    a = MagicMock()
    a.id = action_id
    a.action_id = action_id
    a.title = title
    a.is_preferred = False
    a.provenance = "pylsp-rope"
    a.kind = kind
    return a


def _make_coord(
    *,
    actions: list[Any],
    edit_for: dict[str, dict[str, Any]],
) -> MagicMock:
    coord = MagicMock()
    coord.supports_kind.return_value = True

    async def _merge(**_kw: Any) -> list[Any]:
        return actions

    coord.merge_code_actions = _merge

    def _resolve(aid: str) -> dict[str, Any] | None:
        return edit_for.get(aid)

    coord.get_action_edit = _resolve
    return coord


def _replace_edit(uri: str, sl: int, sc: int, el: int, ec: int, new_text: str) -> dict[str, Any]:
    return {
        "changes": {
            uri: [{
                "range": {
                    "start": {"line": sl, "character": sc},
                    "end": {"line": el, "character": ec},
                },
                "newText": new_text,
            }],
        },
    }


def _insert_edit(uri: str, line: int, ch: int, text: str) -> dict[str, Any]:
    return _replace_edit(uri, line, ch, line, ch, text)


# ---------------------------------------------------------------------------
# 1. InlineTool — single_call_site, position-driven
# ---------------------------------------------------------------------------


def test_g7b_inline_real_disk_single_call_site(tmp_path: Path) -> None:
    src = tmp_path / "main.py"
    src.write_text(
        "def helper():\n    return 42\n\n"
        "def caller():\n    return helper()\n",
        encoding="utf-8",
    )
    before = src.read_text(encoding="utf-8")

    coord = _make_coord(
        actions=[_action(
            "rope:inline",
            "Inline function",
            "refactor.inline.function",
        )],
        edit_for={"rope:inline": _replace_edit(
            src.as_uri(), 4, 11, 4, 19, "42",
        )},
    )
    tool = _make_tool(InlineTool, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 4, "character": 11},
            target="call",
            scope="single_call_site",
            language="python",
        )

    payload = json.loads(out)
    assert payload["applied"] is True, payload
    after = src.read_text(encoding="utf-8")
    assert after != before
    assert "return 42" in after
    # Original `helper()` call site is now `42`:
    assert "return helper()" not in after.split("\n")[4]


# ---------------------------------------------------------------------------
# 2. ImportsOrganizeTool — remove_unused only
# ---------------------------------------------------------------------------


def test_g7b_imports_organize_real_disk_remove_unused(tmp_path: Path) -> None:
    src = tmp_path / "main.py"
    src.write_text(
        "import os\nimport sys\nimport json\n\n"
        "print(sys.argv, os.getcwd())\n",
        encoding="utf-8",
    )
    before = src.read_text(encoding="utf-8")

    coord = _make_coord(
        actions=[_action(
            "rope:rm_unused", "Remove unused imports",
            "source.organizeImports.removeUnused",
        )],
        edit_for={"rope:rm_unused": _replace_edit(
            src.as_uri(), 2, 0, 3, 0, "",
        )},
    )
    tool = _make_tool(ImportsOrganizeTool, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            files=[str(src)],
            add_missing=False, remove_unused=True, reorder=False,
            language="python",
        )

    payload = json.loads(out)
    assert payload["applied"] is True, payload
    after = src.read_text(encoding="utf-8")
    assert after != before
    assert "import json" not in after
    # Other imports preserved:
    assert "import os" in after
    assert "import sys" in after


# ---------------------------------------------------------------------------
# 3. ConvertToMethodObjectTool
# ---------------------------------------------------------------------------


def test_g7b_convert_to_method_object_real_disk(tmp_path: Path) -> None:
    src = tmp_path / "main.py"
    src.write_text(
        "class C:\n    def m(self, x):\n        return x + 1\n",
        encoding="utf-8",
    )
    before = src.read_text(encoding="utf-8")

    coord = _make_coord(
        actions=[_action(
            "rope:mo", "Method to method object",
            "refactor.rewrite.method_to_method_object",
        )],
        edit_for={"rope:mo": _replace_edit(
            src.as_uri(), 0, 0, 3, 0,
            "class _MMethodObject:\n"
            "    def __init__(self, instance, x):\n"
            "        self.instance = instance\n"
            "        self.x = x\n"
            "    def __call__(self):\n"
            "        return self.x + 1\n"
            "class C:\n"
            "    def m(self, x):\n"
            "        return _MMethodObject(self, x)()\n",
        )},
    )
    tool = _make_tool(ConvertToMethodObjectTool, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 1, "character": 8},
            language="python",
        )

    payload = json.loads(out)
    assert payload["applied"] is True, payload
    after = src.read_text(encoding="utf-8")
    assert after != before
    assert "_MMethodObject" in after


# ---------------------------------------------------------------------------
# 4. LocalToFieldTool
# ---------------------------------------------------------------------------


def test_g7b_local_to_field_real_disk(tmp_path: Path) -> None:
    src = tmp_path / "main.py"
    src.write_text(
        "class C:\n    def m(self):\n        x = 1\n        return x\n",
        encoding="utf-8",
    )
    before = src.read_text(encoding="utf-8")

    coord = _make_coord(
        actions=[_action(
            "rope:l2f", "Local to field",
            "refactor.rewrite.local_to_field",
        )],
        edit_for={"rope:l2f": _replace_edit(
            src.as_uri(), 2, 8, 3, 16,
            "self.x = 1\n        return self.x",
        )},
    )
    tool = _make_tool(LocalToFieldTool, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 2, "character": 8},
            language="python",
        )

    payload = json.loads(out)
    assert payload["applied"] is True, payload
    after = src.read_text(encoding="utf-8")
    assert after != before
    assert "self.x" in after


# ---------------------------------------------------------------------------
# 5. UseFunctionTool
# ---------------------------------------------------------------------------


def test_g7b_use_function_real_disk(tmp_path: Path) -> None:
    src = tmp_path / "main.py"
    src.write_text(
        "def doubler(x):\n    return x * 2\n\n"
        "def caller():\n    a = 3 * 2\n    b = 5 * 2\n",
        encoding="utf-8",
    )
    before = src.read_text(encoding="utf-8")

    coord = _make_coord(
        actions=[_action(
            "rope:uf", "Use function",
            "refactor.rewrite.use_function",
        )],
        edit_for={"rope:uf": _replace_edit(
            src.as_uri(), 4, 4, 5, 13,
            "a = doubler(3)\n    b = doubler(5)",
        )},
    )
    tool = _make_tool(UseFunctionTool, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 4},
            language="python",
        )

    payload = json.loads(out)
    assert payload["applied"] is True, payload
    after = src.read_text(encoding="utf-8")
    assert after != before
    assert "doubler(3)" in after
    assert "doubler(5)" in after


# ---------------------------------------------------------------------------
# 6. IntroduceParameterTool — with caller-supplied name
# ---------------------------------------------------------------------------


def test_g7b_introduce_parameter_real_disk_with_caller_name(tmp_path: Path) -> None:
    src = tmp_path / "main.py"
    src.write_text(
        "def f():\n    x = 7\n    return x\n",
        encoding="utf-8",
    )
    before = src.read_text(encoding="utf-8")

    # Rope auto-generates "p"; G6 ME-3 substitutes the caller's name.
    coord = _make_coord(
        actions=[_action(
            "rope:ip", "Introduce parameter",
            "refactor.rewrite.introduce_parameter",
        )],
        edit_for={"rope:ip": _replace_edit(
            src.as_uri(), 0, 0, 3, 0,
            "def f(p=7):\n    x = p\n    return x\n",
        )},
    )
    tool = _make_tool(IntroduceParameterTool, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 1, "character": 4},
            parameter_name="seed",
            language="python",
        )

    payload = json.loads(out)
    assert payload["applied"] is True, payload
    after = src.read_text(encoding="utf-8")
    assert after != before
    # G6 ME-3 substitutes p → seed in the emitted hunk:
    assert "def f(seed=7)" in after
    assert "x = seed" in after


# ---------------------------------------------------------------------------
# 7. GenerateFromUndefinedTool — function target
# ---------------------------------------------------------------------------


def test_g7b_generate_from_undefined_real_disk_function(tmp_path: Path) -> None:
    src = tmp_path / "main.py"
    src.write_text("x = compute()\n", encoding="utf-8")
    before = src.read_text(encoding="utf-8")

    coord = _make_coord(
        actions=[_action(
            "rope:gen_fn", "Generate function 'compute'",
            "quickfix.generate.function",
        )],
        edit_for={"rope:gen_fn": _insert_edit(
            src.as_uri(), 0, 0,
            "def compute():\n    pass\n\n",
        )},
    )
    tool = _make_tool(GenerateFromUndefinedTool, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 4},
            target_kind="function",
            language="python",
        )

    payload = json.loads(out)
    assert payload["applied"] is True, payload
    after = src.read_text(encoding="utf-8")
    assert after != before
    assert "def compute()" in after


# ---------------------------------------------------------------------------
# 8. AutoImportSpecializedTool
# ---------------------------------------------------------------------------


def test_g7b_auto_import_specialized_real_disk(tmp_path: Path) -> None:
    src = tmp_path / "main.py"
    src.write_text("d = OrderedDict()\n", encoding="utf-8")
    before = src.read_text(encoding="utf-8")

    coord = _make_coord(
        actions=[_action(
            "rope:imp", "from collections import OrderedDict",
            "quickfix.import",
        )],
        edit_for={"rope:imp": _insert_edit(
            src.as_uri(), 0, 0,
            "from collections import OrderedDict\n",
        )},
    )
    tool = _make_tool(AutoImportSpecializedTool, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 4},
            symbol_name="OrderedDict",
            language="python",
        )

    payload = json.loads(out)
    assert payload["applied"] is True, payload
    after = src.read_text(encoding="utf-8")
    assert after != before
    assert "from collections import OrderedDict" in after


# ---------------------------------------------------------------------------
# 9. FixLintsTool — single rule dispatch
# ---------------------------------------------------------------------------


def test_g7b_fix_lints_real_disk_dedups_imports(tmp_path: Path) -> None:
    src = tmp_path / "main.py"
    src.write_text(
        "import os\nimport os\n\nprint(os.getcwd())\n",
        encoding="utf-8",
    )
    before = src.read_text(encoding="utf-8")
    assert before.count("import os\n") == 2  # precondition

    coord = _make_coord(
        actions=[_action(
            "ruff:i001", "Remove duplicate imports (I001)",
            "source.fixAll.ruff",
        )],
        edit_for={"ruff:i001": _replace_edit(
            src.as_uri(), 0, 0, 2, 0,
            "import os\n\n",
        )},
    )
    tool = _make_tool(FixLintsTool, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            rules=["I001"],
            language="python",
        )

    payload = json.loads(out)
    assert payload["applied"] is True, payload
    after = src.read_text(encoding="utf-8")
    assert after != before
    assert after.count("import os\n") == 1


# ---------------------------------------------------------------------------
# 10. IgnoreDiagnosticTool — ruff noqa
# ---------------------------------------------------------------------------


def test_g7b_ignore_diagnostic_real_disk_ruff_noqa(tmp_path: Path) -> None:
    src = tmp_path / "main.py"
    src.write_text("import unused_module\n", encoding="utf-8")
    before = src.read_text(encoding="utf-8")

    coord = _make_coord(
        actions=[_action(
            "ruff:noqa", "Disable F401: unused-import",
            "quickfix.ruff_noqa",
        )],
        edit_for={"ruff:noqa": _replace_edit(
            src.as_uri(), 0, 0, 0, 21,
            "import unused_module  # noqa: F401",
        )},
    )
    tool = _make_tool(IgnoreDiagnosticTool, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 7},
            tool_name="ruff",
            rule="F401",
            language="python",
        )

    payload = json.loads(out)
    assert payload["applied"] is True, payload
    after = src.read_text(encoding="utf-8")
    assert after != before
    assert "noqa: F401" in after
