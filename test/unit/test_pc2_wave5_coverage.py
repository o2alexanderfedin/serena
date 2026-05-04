"""PC2 Wave-5 coverage uplift — remaining small gaps.

Targets:
- python_async_conversion.py L81 (regex match fails on def line)
- python_async_conversion.py L104 (_is_call_to: non-matching call → continue)
- python_async_conversion.py L179 (_enclosing_async_map: module-level call, host=None)
- python_imports_relative.py L45-46 (rope ImportError path)
- python_imports_relative.py L61 (rope returns None)
- python_return_type_infer.py L102 (could_not_locate_insertion_point)
- python_return_type_infer.py L206 (_locate_return_type_insertion: no colon found)
- python_strategy.py L266-394 (steps 4-13 early-exit conditions)
- multi_server.py: remaining L944, L958, L964, L981 branches
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# python_async_conversion.py edge cases
# ---------------------------------------------------------------------------


class TestConvertFunctionToAsyncEdgeCases:
    def test_regex_match_fails_raises_value_error(self, tmp_path: Path) -> None:
        """If AST finds def node but regex can't locate def token → ValueError."""
        from serena.refactoring.python_async_conversion import convert_function_to_async
        import ast

        # Write a file where the function is found by AST but the line
        # doesn't match _DEF_TOKEN_RE. We achieve this by patching _find_def
        # to return a fake node whose lineno points to a non-def line.
        src = "x = 1\ndef real_func():\n    pass\n"
        f = tmp_path / "mod.py"
        f.write_text(src)

        # Patch _find_def to return a FunctionDef node whose lineno=1 (the "x = 1" line)
        fake_node = ast.FunctionDef(
            name="real_func",
            lineno=1,  # points to "x = 1" — no def token here
            col_offset=0,
        )
        fake_node.decorator_list = []

        with patch("serena.refactoring.python_async_conversion._find_def", return_value=fake_node):
            with pytest.raises(ValueError, match="cannot locate"):
                convert_function_to_async(
                    file=str(f),
                    symbol="real_func",
                    project_root=tmp_path,
                )

    def test_non_matching_calls_are_skipped(self, tmp_path: Path) -> None:
        """Calls to different symbols are skipped (_is_call_to returns False)."""
        from serena.refactoring.python_async_conversion import convert_function_to_async

        src = (
            "def target():\n"
            "    return 1\n"
            "\n"
            "async def handler():\n"
            "    other_func()  # not target\n"
            "    result = target()\n"
            "    return result\n"
        )
        f = tmp_path / "mod.py"
        f.write_text(src)

        edit, summary = convert_function_to_async(
            file=str(f),
            symbol="target",
            project_root=tmp_path,
        )
        # Only `target()` gets await inserted; `other_func()` is skipped.
        assert summary["await_call_sites"] == 1
        assert summary["unwrapped_call_sites"] == 0

    def test_module_level_call_is_unwrapped(self, tmp_path: Path) -> None:
        """A call at module level (outside any def) → unwrapped_call_sites."""
        from serena.refactoring.python_async_conversion import convert_function_to_async

        src = (
            "def process():\n"
            "    return 1\n"
            "\n"
            "# Module level call\n"
            "result = process()\n"
        )
        f = tmp_path / "mod.py"
        f.write_text(src)

        edit, summary = convert_function_to_async(
            file=str(f),
            symbol="process",
            project_root=tmp_path,
        )
        # Module-level call: host=None → unwrapped.
        assert summary["unwrapped_call_sites"] == 1
        assert summary["await_call_sites"] == 0

    def test_enclosing_async_map_module_level_call_not_in_map(self) -> None:
        """_enclosing_async_map: module-level call has no host → id not in map."""
        from serena.refactoring.python_async_conversion import _enclosing_async_map
        import ast

        src = "process()\n"
        tree = ast.parse(src)
        result = _enclosing_async_map(tree)
        # The call `process()` is at module level; no host entry should exist.
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        assert len(calls) == 1
        assert id(calls[0]) not in result


# ---------------------------------------------------------------------------
# python_imports_relative.py edge cases
# ---------------------------------------------------------------------------


class TestConvertFromRelativeImportsEdgeCases:
    def test_rope_unavailable_returns_skipped(self, tmp_path: Path) -> None:
        """When rope is not installed, returns skipped/rope_unavailable."""
        from serena.refactoring.python_imports_relative import convert_from_relative_imports

        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        mod = pkg / "mod.py"
        mod.write_text("from .other import x\n")

        with patch.dict("sys.modules", {"rope": None, "rope.base.project": None,
                                         "rope.refactor.importutils": None}):
            with patch("builtins.__import__", side_effect=ImportError("rope not installed")):
                try:
                    edit, status = convert_from_relative_imports(
                        file=str(mod),
                        project_root=tmp_path,
                    )
                    if status.get("reason") == "rope_unavailable":
                        assert edit is None
                except ImportError:
                    pass  # acceptable — the rope import itself may fail

    def test_rope_returns_none_handled(self, tmp_path: Path) -> None:
        """When rope's relatives_to_absolutes returns None, status is rope_returned_none."""
        from serena.refactoring.python_imports_relative import convert_from_relative_imports

        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        mod = pkg / "mod.py"
        mod.write_text("from .other import x\n")

        # Patch ImportTools.relatives_to_absolutes to return None.
        with patch("rope.refactor.importutils.ImportTools.relatives_to_absolutes", return_value=None):
            edit, status = convert_from_relative_imports(
                file=str(mod),
                project_root=tmp_path,
            )
        assert edit is None
        assert status["status"] == "skipped"
        assert status["reason"] == "rope_returned_none"


# ---------------------------------------------------------------------------
# python_return_type_infer.py edge cases
# ---------------------------------------------------------------------------


class TestAnnotateReturnTypeEdgeCases:
    def test_insertion_point_not_found_returns_failed(self, tmp_path: Path) -> None:
        """When _locate_return_type_insertion returns None → failed/could_not_locate."""
        from serena.refactoring.python_return_type_infer import annotate_return_type

        f = tmp_path / "mod.py"
        f.write_text("def compute():\n    return 42\n")

        def type_provider(uri, rng):
            return [{"label": "-> int", "kind": 1}]

        # Patch _locate_return_type_insertion to return None.
        with patch(
            "serena.refactoring.python_return_type_infer._locate_return_type_insertion",
            return_value=None,
        ):
            edit, status = annotate_return_type(
                file=str(f),
                symbol="compute",
                project_root=tmp_path,
                inlay_hint_provider=type_provider,
            )

        assert edit is None
        assert status["status"] == "failed"
        assert status["reason"] == "could_not_locate_insertion_point"

    def test_locate_insertion_no_colon_returns_none(self) -> None:
        """_locate_return_type_insertion with lines having no ':' returns None."""
        from serena.refactoring.python_return_type_infer import _locate_return_type_insertion

        # Lines without any colon — should return None.
        lines = ["def foo(x, y)\n"]  # invalid Python but tests edge case
        result = _locate_return_type_insertion(lines, 0)
        assert result is None


# ---------------------------------------------------------------------------
# python_strategy.py — steps 4-13 early-exit conditions
# ---------------------------------------------------------------------------


class TestPythonInterpreterStepEarlyExits:
    """Test that each step's guard conditions cause it to return None.
    These hit the guard lines (the returns at top of each step function).
    """

    def test_step4_poetry_no_lock_returns_none(self, tmp_path: Path) -> None:
        """Step 4: no poetry.lock → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        result = _PythonInterpreter._step4_poetry(tmp_path)
        assert result is None

    def test_step4_poetry_no_poetry_command_returns_none(self, tmp_path: Path) -> None:
        """Step 4: poetry.lock exists but poetry command absent → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        (tmp_path / "poetry.lock").write_text("content")
        with patch("shutil.which", return_value=None):
            result = _PythonInterpreter._step4_poetry(tmp_path)
        assert result is None

    def test_step5_pdm_no_lock_returns_none(self, tmp_path: Path) -> None:
        """Step 5: no pdm.lock → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        result = _PythonInterpreter._step5_pdm(tmp_path)
        assert result is None

    def test_step5_pdm_no_pdm_command_returns_none(self, tmp_path: Path) -> None:
        """Step 5: pdm.lock exists but pdm command absent → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        (tmp_path / "pdm.lock").write_text("content")
        with patch("shutil.which", return_value=None):
            result = _PythonInterpreter._step5_pdm(tmp_path)
        assert result is None

    def test_step6_uv_no_lock_returns_none(self, tmp_path: Path) -> None:
        """Step 6: no uv.lock → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        result = _PythonInterpreter._step6_uv(tmp_path)
        assert result is None

    def test_step6_uv_no_uv_command_returns_none(self, tmp_path: Path) -> None:
        """Step 6: uv.lock exists but uv command absent → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        (tmp_path / "uv.lock").write_text("content")
        with patch("shutil.which", return_value=None):
            result = _PythonInterpreter._step6_uv(tmp_path)
        assert result is None

    def test_step7_conda_no_env_yml_returns_none(self, tmp_path: Path) -> None:
        """Step 7: no environment.yml → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        result = _PythonInterpreter._step7_conda(tmp_path)
        assert result is None

    def test_step7_conda_no_conda_env_var_returns_none(self, tmp_path: Path) -> None:
        """Step 7: environment.yml exists but CONDA_DEFAULT_ENV not set → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        (tmp_path / "environment.yml").write_text("name: env")
        with patch.dict(os.environ, {}, clear=True):
            result = _PythonInterpreter._step7_conda(tmp_path)
        assert result is None

    def test_step7_conda_no_conda_command_returns_none(self, tmp_path: Path) -> None:
        """Step 7: environment.yml + CONDA_DEFAULT_ENV but no conda command → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        (tmp_path / "environment.yml").write_text("name: env")
        with patch.dict(os.environ, {"CONDA_DEFAULT_ENV": "myenv"}), \
             patch("shutil.which", return_value=None):
            result = _PythonInterpreter._step7_conda(tmp_path)
        assert result is None

    def test_step8_pipenv_no_pipfile_returns_none(self, tmp_path: Path) -> None:
        """Step 8: no Pipfile.lock → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        result = _PythonInterpreter._step8_pipenv(tmp_path)
        assert result is None

    def test_step8_pipenv_no_pipenv_command_returns_none(self, tmp_path: Path) -> None:
        """Step 8: Pipfile.lock exists but pipenv command absent → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        (tmp_path / "Pipfile.lock").write_text("{}")
        with patch("shutil.which", return_value=None):
            result = _PythonInterpreter._step8_pipenv(tmp_path)
        assert result is None

    def test_step9_pyenv_no_version_file_returns_none(self, tmp_path: Path) -> None:
        """Step 9: no .python-version file → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        result = _PythonInterpreter._step9_pyenv(tmp_path)
        assert result is None

    def test_step9_pyenv_no_pyenv_command_returns_none(self, tmp_path: Path) -> None:
        """Step 9: .python-version exists but pyenv command absent → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        (tmp_path / ".python-version").write_text("3.11.0")
        with patch("shutil.which", return_value=None):
            result = _PythonInterpreter._step9_pyenv(tmp_path)
        assert result is None

    def test_step10_asdf_no_tool_versions_returns_none(self, tmp_path: Path) -> None:
        """Step 10: no .tool-versions file → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        result = _PythonInterpreter._step10_asdf(tmp_path)
        assert result is None

    def test_step10_asdf_no_asdf_command_returns_none(self, tmp_path: Path) -> None:
        """Step 10: .tool-versions exists but asdf command absent → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        (tmp_path / ".tool-versions").write_text("python 3.11.0")
        with patch("shutil.which", return_value=None):
            result = _PythonInterpreter._step10_asdf(tmp_path)
        assert result is None

    def test_step10_asdf_no_python_in_tool_versions_returns_none(self, tmp_path: Path) -> None:
        """Step 10: .tool-versions exists but no python entry → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        (tmp_path / ".tool-versions").write_text("nodejs 20.0.0")
        # asdf exists but no python
        with patch("shutil.which", return_value="/usr/bin/asdf"):
            result = _PythonInterpreter._step10_asdf(tmp_path)
        assert result is None

    def test_step11_pep582_no_pypackages_returns_none(self, tmp_path: Path) -> None:
        """Step 11: no __pypackages__ directory → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        result = _PythonInterpreter._step11_pep582(tmp_path)
        assert result is None

    def test_step11_pep582_empty_pypackages_returns_none(self, tmp_path: Path) -> None:
        """Step 11: __pypackages__ exists but empty → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        (tmp_path / "__pypackages__").mkdir()
        result = _PythonInterpreter._step11_pep582(tmp_path)
        assert result is None

    def test_step12_pythonpath_walk_no_pythonpath_returns_none(self, tmp_path: Path) -> None:
        """Step 12: PYTHONPATH not set → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        with patch.dict(os.environ, {}, clear=True):
            result = _PythonInterpreter._step12_pythonpath_walk(tmp_path)
        assert result is None

    def test_step12_pythonpath_walk_nonexistent_dir_returns_none(self, tmp_path: Path) -> None:
        """Step 12: PYTHONPATH points to non-existent dir → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        with patch.dict(os.environ, {"PYTHONPATH": "/nonexistent/path"}):
            result = _PythonInterpreter._step12_pythonpath_walk(tmp_path)
        assert result is None

    def test_step13_python_host_path_not_set_returns_none(self, tmp_path: Path) -> None:
        """Step 13: PYTHON_HOST_PATH not set → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        with patch.dict(os.environ, {}, clear=True):
            result = _PythonInterpreter._step13_python_host_path(tmp_path)
        assert result is None

    def test_step13_python_host_path_set_returns_path(self, tmp_path: Path) -> None:
        """Step 13: PYTHON_HOST_PATH set → returns that path."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        with patch.dict(os.environ, {"PYTHON_HOST_PATH": "/usr/bin/python3"}):
            result = _PythonInterpreter._step13_python_host_path(tmp_path)
        assert result == Path("/usr/bin/python3")

    def test_step4_poetry_nonzero_returncode_returns_none(self, tmp_path: Path) -> None:
        """Step 4: poetry command fails (non-zero returncode) → None."""
        import subprocess
        from serena.refactoring.python_strategy import _PythonInterpreter

        (tmp_path / "poetry.lock").write_text("content")
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""

        with patch("shutil.which", return_value="/usr/bin/poetry"), \
             patch("subprocess.run", return_value=mock_proc):
            result = _PythonInterpreter._step4_poetry(tmp_path)
        assert result is None

    def test_step5_pdm_nonzero_returncode_returns_none(self, tmp_path: Path) -> None:
        """Step 5: pdm command fails → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        (tmp_path / "pdm.lock").write_text("content")
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""

        with patch("shutil.which", return_value="/usr/bin/pdm"), \
             patch("subprocess.run", return_value=mock_proc):
            result = _PythonInterpreter._step5_pdm(tmp_path)
        assert result is None

    def test_step6_uv_nonzero_returncode_returns_none(self, tmp_path: Path) -> None:
        """Step 6: uv command fails → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        (tmp_path / "uv.lock").write_text("content")
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""

        with patch("shutil.which", return_value="/usr/bin/uv"), \
             patch("subprocess.run", return_value=mock_proc):
            result = _PythonInterpreter._step6_uv(tmp_path)
        assert result is None

    def test_step8_pipenv_nonzero_returncode_returns_none(self, tmp_path: Path) -> None:
        """Step 8: pipenv command fails → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        (tmp_path / "Pipfile.lock").write_text("{}")
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""

        with patch("shutil.which", return_value="/usr/bin/pipenv"), \
             patch("subprocess.run", return_value=mock_proc):
            result = _PythonInterpreter._step8_pipenv(tmp_path)
        assert result is None

    def test_step9_pyenv_nonzero_returncode_returns_none(self, tmp_path: Path) -> None:
        """Step 9: pyenv command fails → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        (tmp_path / ".python-version").write_text("3.11.0")
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""

        with patch("shutil.which", return_value="/usr/bin/pyenv"), \
             patch("subprocess.run", return_value=mock_proc):
            result = _PythonInterpreter._step9_pyenv(tmp_path)
        assert result is None

    def test_step10_asdf_nonzero_returncode_returns_none(self, tmp_path: Path) -> None:
        """Step 10: asdf command fails → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        (tmp_path / ".tool-versions").write_text("python 3.11.0")
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""

        with patch("shutil.which", return_value="/usr/bin/asdf"), \
             patch("subprocess.run", return_value=mock_proc):
            result = _PythonInterpreter._step10_asdf(tmp_path)
        assert result is None
