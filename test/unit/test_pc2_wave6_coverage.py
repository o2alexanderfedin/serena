"""PC2 Wave-6 coverage uplift.

Targets:
- clippy_adapter.py (0% → 85%+) — pure Python JSON parsing
- python_strategy.py steps 4-13 success paths (subprocess mocked to succeed)
- python_strategy.py RopeBridge L563-582 (move_module), L616-642 (move_global)
- multi_server.py L1893 (EditAttributionLog.replay edge case)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# clippy_adapter.py — ClippyUnavailableError + clippy_json_to_workspace_edit
# ---------------------------------------------------------------------------


class TestClippyAdapter:
    def test_diagnostics_as_workspace_edit_raises_when_cargo_missing(self, tmp_path: Path) -> None:
        from serena.refactoring.clippy_adapter import ClippyAdapter, ClippyUnavailableError

        adapter = ClippyAdapter(workspace=tmp_path)
        with patch("shutil.which", return_value=None):
            with pytest.raises(ClippyUnavailableError, match="cargo not found"):
                adapter.diagnostics_as_workspace_edit()

    def test_diagnostics_as_workspace_edit_calls_cargo_and_parses(self, tmp_path: Path) -> None:
        from serena.refactoring.clippy_adapter import ClippyAdapter

        # Minimal compiler-message with a suggestion.
        record = {
            "reason": "compiler-message",
            "message": {
                "code": {"code": "clippy::unused_variable"},
                "message": "unused variable: x",
                "spans": [
                    {
                        "file_name": "src/main.rs",
                        "line_start": 3,
                        "column_start": 5,
                        "line_end": 3,
                        "column_end": 6,
                        "suggested_replacement": "_x",
                        "suggestion_applicability": "MachineApplicable",
                    }
                ],
            },
        }
        stdout = json.dumps(record) + "\n"

        mock_proc = MagicMock()
        mock_proc.stdout = stdout

        with patch("shutil.which", return_value="/usr/bin/cargo"), \
             patch("subprocess.run", return_value=mock_proc):
            adapter = ClippyAdapter(workspace=tmp_path)
            result = adapter.diagnostics_as_workspace_edit()

        assert "documentChanges" in result
        assert len(result["documentChanges"]) == 1
        assert result["documentChanges"][0]["edits"][0]["newText"] == "_x"


class TestClippyJsonToWorkspaceEdit:
    def _make_record(
        self,
        lint_name: str = "clippy::unused_variable",
        replacement: str = "_x",
        applicability: str = "MachineApplicable",
        file_name: str = "src/main.rs",
    ) -> dict:
        return {
            "reason": "compiler-message",
            "message": {
                "code": {"code": lint_name},
                "message": "lint description",
                "spans": [
                    {
                        "file_name": file_name,
                        "line_start": 3,
                        "column_start": 5,
                        "line_end": 3,
                        "column_end": 6,
                        "suggested_replacement": replacement,
                        "suggestion_applicability": applicability,
                    }
                ],
            },
        }

    def test_empty_stdout_returns_empty_edit(self, tmp_path: Path) -> None:
        from serena.refactoring.clippy_adapter import clippy_json_to_workspace_edit

        result = clippy_json_to_workspace_edit("", tmp_path)
        assert result == {"documentChanges": []}

    def test_non_compiler_message_is_skipped(self, tmp_path: Path) -> None:
        from serena.refactoring.clippy_adapter import clippy_json_to_workspace_edit

        record = {"reason": "build-finished", "success": True}
        stdout = json.dumps(record) + "\n"
        result = clippy_json_to_workspace_edit(stdout, tmp_path)
        assert result == {"documentChanges": []}

    def test_invalid_json_is_skipped(self, tmp_path: Path) -> None:
        from serena.refactoring.clippy_adapter import clippy_json_to_workspace_edit

        stdout = "not json\n{invalid}\n"
        result = clippy_json_to_workspace_edit(stdout, tmp_path)
        assert result == {"documentChanges": []}

    def test_non_dict_record_is_skipped(self, tmp_path: Path) -> None:
        from serena.refactoring.clippy_adapter import clippy_json_to_workspace_edit

        stdout = json.dumps([1, 2, 3]) + "\n"
        result = clippy_json_to_workspace_edit(stdout, tmp_path)
        assert result == {"documentChanges": []}

    def test_valid_suggestion_produces_document_change(self, tmp_path: Path) -> None:
        from serena.refactoring.clippy_adapter import clippy_json_to_workspace_edit

        record = self._make_record()
        stdout = json.dumps(record) + "\n"
        result = clippy_json_to_workspace_edit(stdout, tmp_path)
        assert len(result["documentChanges"]) == 1
        dc = result["documentChanges"][0]
        assert dc["textDocument"]["version"] is None
        assert dc["edits"][0]["newText"] == "_x"
        assert "changeAnnotations" in result
        assert "clippy::unused_variable" in result["changeAnnotations"]

    def test_span_without_replacement_is_skipped(self, tmp_path: Path) -> None:
        from serena.refactoring.clippy_adapter import clippy_json_to_workspace_edit

        record = {
            "reason": "compiler-message",
            "message": {
                "code": {"code": "clippy::foo"},
                "message": "foo",
                "spans": [
                    {
                        "file_name": "src/main.rs",
                        "line_start": 1,
                        "column_start": 1,
                        "line_end": 1,
                        "column_end": 2,
                        # NO suggested_replacement
                        "suggestion_applicability": "MachineApplicable",
                    }
                ],
            },
        }
        stdout = json.dumps(record) + "\n"
        result = clippy_json_to_workspace_edit(stdout, tmp_path)
        assert result == {"documentChanges": []}

    def test_unspecified_applicability_still_included(self, tmp_path: Path) -> None:
        """Unspecified applicability: span is still included but with annotation."""
        from serena.refactoring.clippy_adapter import clippy_json_to_workspace_edit

        record = self._make_record(applicability="Unspecified")
        stdout = json.dumps(record) + "\n"
        result = clippy_json_to_workspace_edit(stdout, tmp_path)
        # Still included — the code just `pass`es the "Unspecified" check.
        assert len(result["documentChanges"]) == 1

    def test_lint_name_none_uses_default(self, tmp_path: Path) -> None:
        """When code is absent/None, lint_name defaults to clippy::unknown."""
        from serena.refactoring.clippy_adapter import clippy_json_to_workspace_edit

        record = {
            "reason": "compiler-message",
            "message": {
                "code": None,  # no code
                "message": "some error",
                "spans": [
                    {
                        "file_name": "src/main.rs",
                        "line_start": 1,
                        "column_start": 1,
                        "line_end": 1,
                        "column_end": 2,
                        "suggested_replacement": "fix",
                        "suggestion_applicability": "MachineApplicable",
                    }
                ],
            },
        }
        stdout = json.dumps(record) + "\n"
        result = clippy_json_to_workspace_edit(stdout, tmp_path)
        assert len(result["documentChanges"]) == 1
        assert "clippy::unknown" in result["changeAnnotations"]

    def test_non_dict_message_is_skipped(self, tmp_path: Path) -> None:
        from serena.refactoring.clippy_adapter import clippy_json_to_workspace_edit

        record = {"reason": "compiler-message", "message": "not a dict"}
        stdout = json.dumps(record) + "\n"
        result = clippy_json_to_workspace_edit(stdout, tmp_path)
        assert result == {"documentChanges": []}

    def test_non_dict_span_is_skipped(self, tmp_path: Path) -> None:
        from serena.refactoring.clippy_adapter import clippy_json_to_workspace_edit

        record = {
            "reason": "compiler-message",
            "message": {
                "code": {"code": "clippy::foo"},
                "message": "foo",
                "spans": ["not a dict"],  # non-dict span
            },
        }
        stdout = json.dumps(record) + "\n"
        result = clippy_json_to_workspace_edit(stdout, tmp_path)
        assert result == {"documentChanges": []}

    def test_non_string_file_name_is_skipped(self, tmp_path: Path) -> None:
        from serena.refactoring.clippy_adapter import clippy_json_to_workspace_edit

        record = {
            "reason": "compiler-message",
            "message": {
                "code": {"code": "clippy::foo"},
                "message": "foo",
                "spans": [
                    {
                        "file_name": 42,  # not a string
                        "line_start": 1,
                        "column_start": 1,
                        "line_end": 1,
                        "column_end": 2,
                        "suggested_replacement": "fix",
                        "suggestion_applicability": "MachineApplicable",
                    }
                ],
            },
        }
        stdout = json.dumps(record) + "\n"
        result = clippy_json_to_workspace_edit(stdout, tmp_path)
        assert result == {"documentChanges": []}

    def test_multiple_suggestions_merged_per_file(self, tmp_path: Path) -> None:
        """Multiple suggestions for the same file are merged into one documentChange."""
        from serena.refactoring.clippy_adapter import clippy_json_to_workspace_edit

        record1 = self._make_record(replacement="_x", lint_name="clippy::foo")
        record2 = self._make_record(replacement="_y", lint_name="clippy::bar",
                                     file_name="src/main.rs")
        stdout = json.dumps(record1) + "\n" + json.dumps(record2) + "\n"
        result = clippy_json_to_workspace_edit(stdout, tmp_path)
        # Both edits go to the same file → merged into one documentChange.
        assert len(result["documentChanges"]) == 1
        assert len(result["documentChanges"][0]["edits"]) == 2

    def test_blank_lines_in_stdout_are_skipped(self, tmp_path: Path) -> None:
        from serena.refactoring.clippy_adapter import clippy_json_to_workspace_edit

        record = self._make_record()
        stdout = "\n\n" + json.dumps(record) + "\n\n"
        result = clippy_json_to_workspace_edit(stdout, tmp_path)
        assert len(result["documentChanges"]) == 1

    def test_code_integer_lint_name_defaults_to_unknown(self, tmp_path: Path) -> None:
        """When code.code is not a string (e.g. int), lint_name → clippy::unknown."""
        from serena.refactoring.clippy_adapter import clippy_json_to_workspace_edit

        record = {
            "reason": "compiler-message",
            "message": {
                "code": {"code": 42},  # integer code
                "message": "some error",
                "spans": [
                    {
                        "file_name": "src/main.rs",
                        "line_start": 1,
                        "column_start": 1,
                        "line_end": 1,
                        "column_end": 2,
                        "suggested_replacement": "fix",
                        "suggestion_applicability": "MachineApplicable",
                    }
                ],
            },
        }
        stdout = json.dumps(record) + "\n"
        result = clippy_json_to_workspace_edit(stdout, tmp_path)
        assert "clippy::unknown" in result["changeAnnotations"]


class TestSpanToRange:
    def test_converts_1based_to_0based(self) -> None:
        from serena.refactoring.clippy_adapter import _span_to_range

        span = {
            "line_start": 3,
            "column_start": 5,
            "line_end": 3,
            "column_end": 6,
        }
        result = _span_to_range(span)
        assert result["start"]["line"] == 2
        assert result["start"]["character"] == 4
        assert result["end"]["line"] == 2
        assert result["end"]["character"] == 5

    def test_clamps_negative_to_zero(self) -> None:
        from serena.refactoring.clippy_adapter import _span_to_range

        span = {
            "line_start": 0,  # 0 → clamped to 0 (already valid after -1)
            "column_start": 0,
            "line_end": 0,
            "column_end": 0,
        }
        result = _span_to_range(span)
        assert result["start"]["line"] == 0
        assert result["start"]["character"] == 0

    def test_defaults_when_keys_absent(self) -> None:
        from serena.refactoring.clippy_adapter import _span_to_range

        # All keys absent — defaults kick in.
        result = _span_to_range({})
        assert result["start"]["line"] == 0
        assert result["start"]["character"] == 0


# ---------------------------------------------------------------------------
# python_strategy.py steps 4-13 — success paths
# ---------------------------------------------------------------------------


class TestPythonInterpreterStepSuccessPaths:
    def test_step4_poetry_succeeds_when_venv_python_exists(self, tmp_path: Path) -> None:
        """Step 4: poetry command succeeds and venv has python binary."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        venv_root = tmp_path / "venv"
        bin_dir = venv_root / "bin"
        bin_dir.mkdir(parents=True)
        python_bin = bin_dir / "python"
        python_bin.write_text("#!/bin/bash\n")

        (tmp_path / "poetry.lock").write_text("content")
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = str(venv_root) + "\n"

        with patch("shutil.which", return_value="/usr/bin/poetry"), \
             patch("subprocess.run", return_value=mock_proc):
            result = _PythonInterpreter._step4_poetry(tmp_path)
        assert result == python_bin

    def test_step4_poetry_venv_python_missing_returns_none(self, tmp_path: Path) -> None:
        """Step 4: poetry command succeeds but venv doesn't have python binary."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        venv_root = tmp_path / "empty_venv"
        # Don't create the bin/python file.

        (tmp_path / "poetry.lock").write_text("content")
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = str(venv_root) + "\n"

        with patch("shutil.which", return_value="/usr/bin/poetry"), \
             patch("subprocess.run", return_value=mock_proc):
            result = _PythonInterpreter._step4_poetry(tmp_path)
        assert result is None

    def test_step5_pdm_succeeds(self, tmp_path: Path) -> None:
        """Step 5: pdm info succeeds and returns a path."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        python_path = tmp_path / "python3"
        python_path.write_text("#!/bin/bash\n")

        (tmp_path / "pdm.lock").write_text("content")
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = str(python_path) + "\n"

        with patch("shutil.which", return_value="/usr/bin/pdm"), \
             patch("subprocess.run", return_value=mock_proc):
            result = _PythonInterpreter._step5_pdm(tmp_path)
        assert result == python_path

    def test_step6_uv_succeeds(self, tmp_path: Path) -> None:
        """Step 6: uv python find succeeds and returns a path."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        python_path = tmp_path / "python3"
        python_path.write_text("#!/bin/bash\n")

        (tmp_path / "uv.lock").write_text("content")
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = str(python_path) + "\n"

        with patch("shutil.which", return_value="/usr/bin/uv"), \
             patch("subprocess.run", return_value=mock_proc):
            result = _PythonInterpreter._step6_uv(tmp_path)
        assert result == python_path

    def test_step7_conda_succeeds_with_matching_env(self, tmp_path: Path) -> None:
        """Step 7: conda info --envs output has matching env name."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        # Create a fake Python binary to test cand.exists()
        env_dir = tmp_path / "conda_env"
        bin_dir = env_dir / "bin"
        bin_dir.mkdir(parents=True)
        python_bin = bin_dir / "python"
        python_bin.write_text("#!/bin/bash\n")

        (tmp_path / "environment.yml").write_text("name: myenv")

        mock_proc = MagicMock()
        mock_proc.stdout = f"myenv  {str(env_dir)}\nbase   /usr/bin\n"

        with patch.dict(os.environ, {"CONDA_DEFAULT_ENV": "myenv"}), \
             patch("shutil.which", return_value="/usr/bin/conda"), \
             patch("subprocess.run", return_value=mock_proc):
            result = _PythonInterpreter._step7_conda(tmp_path)
        # The candidate is env_dir / bin / python which we created.
        assert result == python_bin

    def test_step7_conda_env_not_in_output_returns_none(self, tmp_path: Path) -> None:
        """Step 7: conda info output doesn't contain the env name → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        (tmp_path / "environment.yml").write_text("name: myenv")

        mock_proc = MagicMock()
        mock_proc.stdout = "base   /usr/bin\nother_env  /other\n"

        with patch.dict(os.environ, {"CONDA_DEFAULT_ENV": "myenv"}), \
             patch("shutil.which", return_value="/usr/bin/conda"), \
             patch("subprocess.run", return_value=mock_proc):
            result = _PythonInterpreter._step7_conda(tmp_path)
        assert result is None

    def test_step8_pipenv_succeeds(self, tmp_path: Path) -> None:
        """Step 8: pipenv --py succeeds and returns a path."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        python_path = tmp_path / "python3"
        python_path.write_text("#!/bin/bash\n")

        (tmp_path / "Pipfile.lock").write_text("{}")
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = str(python_path) + "\n"

        with patch("shutil.which", return_value="/usr/bin/pipenv"), \
             patch("subprocess.run", return_value=mock_proc):
            result = _PythonInterpreter._step8_pipenv(tmp_path)
        assert result == python_path

    def test_step9_pyenv_succeeds(self, tmp_path: Path) -> None:
        """Step 9: pyenv which python succeeds and returns a path."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        python_path = tmp_path / "python3"
        python_path.write_text("#!/bin/bash\n")

        (tmp_path / ".python-version").write_text("3.11.0")
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = str(python_path) + "\n"

        with patch("shutil.which", return_value="/usr/bin/pyenv"), \
             patch("subprocess.run", return_value=mock_proc):
            result = _PythonInterpreter._step9_pyenv(tmp_path)
        assert result == python_path

    def test_step10_asdf_succeeds(self, tmp_path: Path) -> None:
        """Step 10: asdf where python succeeds and returns a path."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        python_dir = tmp_path / "asdf_python"
        bin_dir = python_dir / "bin"
        bin_dir.mkdir(parents=True)
        python_bin = bin_dir / "python"
        python_bin.write_text("#!/bin/bash\n")

        (tmp_path / ".tool-versions").write_text("python 3.11.0")
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = str(python_dir) + "\n"

        with patch("shutil.which", return_value="/usr/bin/asdf"), \
             patch("subprocess.run", return_value=mock_proc):
            result = _PythonInterpreter._step10_asdf(tmp_path)
        assert result == python_bin

    def test_step11_pep582_with_pypackages_version_dir(self, tmp_path: Path) -> None:
        """Step 11: __pypackages__/3.11/lib exists + python3.11 on PATH → path."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        pp = tmp_path / "__pypackages__"
        ver_dir = pp / "3.11"
        lib_dir = ver_dir / "lib"
        lib_dir.mkdir(parents=True)

        with patch("shutil.which", return_value="/usr/bin/python3.11"):
            result = _PythonInterpreter._step11_pep582(tmp_path)
        assert result == Path("/usr/bin/python3.11")

    def test_step11_pep582_no_python_on_path_returns_none(self, tmp_path: Path) -> None:
        """Step 11: __pypackages__ exists with version dir but no python → None."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        pp = tmp_path / "__pypackages__"
        ver_dir = pp / "3.11"
        lib_dir = ver_dir / "lib"
        lib_dir.mkdir(parents=True)

        with patch("shutil.which", return_value=None):
            result = _PythonInterpreter._step11_pep582(tmp_path)
        assert result is None

    def test_step12_pythonpath_walk_with_dist_info(self, tmp_path: Path) -> None:
        """Step 12: PYTHONPATH has a dist-info → returns python3 from PATH."""
        from serena.refactoring.python_strategy import _PythonInterpreter

        # Create a minimal dist-info directory.
        dist_info = tmp_path / "some_pkg-1.0.dist-info"
        dist_info.mkdir()
        (dist_info / "METADATA").write_text("Name: some_pkg\n")

        with patch.dict(os.environ, {"PYTHONPATH": str(tmp_path)}), \
             patch("shutil.which", return_value="/usr/bin/python3"):
            result = _PythonInterpreter._step12_pythonpath_walk(tmp_path)
        assert result == Path("/usr/bin/python3")


# ---------------------------------------------------------------------------
# multi_server.py L1893 — EditAttributionLog.replay edge cases
# ---------------------------------------------------------------------------


class TestEditAttributionLogReplay:
    def test_replay_empty_when_log_missing(self, tmp_path: Path) -> None:
        from serena.refactoring.multi_server import EditAttributionLog

        log = EditAttributionLog(tmp_path)
        records = list(log.replay())
        assert records == []

    def test_replay_yields_records_from_log(self, tmp_path: Path) -> None:
        """replay() yields valid JSONL records; blank lines are skipped."""
        from serena.refactoring.multi_server import EditAttributionLog
        import asyncio

        log = EditAttributionLog(tmp_path)
        # Append a record.
        asyncio.run(log.append(
            checkpoint_id="ckpt-1",
            tool="test_tool",
            server="pylsp-rope",
            edit={
                "documentChanges": [{
                    "textDocument": {"uri": "file:///a.py", "version": None},
                    "edits": [{"range": {"start": {"line": 0, "character": 0},
                                         "end": {"line": 0, "character": 3}}, "newText": "new"}],
                }]
            },
        ))
        records = list(log.replay())
        assert len(records) == 1
        assert records[0]["checkpoint_id"] == "ckpt-1"

    def test_replay_skips_blank_lines(self, tmp_path: Path) -> None:
        """Blank lines in the log file are skipped."""
        from serena.refactoring.multi_server import EditAttributionLog

        log = EditAttributionLog(tmp_path)
        log.path.parent.mkdir(parents=True, exist_ok=True)
        # Write file with blank lines manually.
        with log.path.open("w") as f:
            f.write('\n\n{"checkpoint_id": "c1", "tool": "t"}\n\n')

        records = list(log.replay())
        assert len(records) == 1
        assert records[0]["checkpoint_id"] == "c1"
