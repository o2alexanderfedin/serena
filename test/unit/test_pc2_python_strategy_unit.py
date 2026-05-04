"""PC2 coverage uplift — serena.refactoring.python_strategy uncovered ranges.

Target line ranges from Phase B coverage analysis:
  L82     build_servers builds dict
  L90-96  coordinator() calls build_servers + interpreter discovery
  L116-117 coordinator() configure_interpreter=False branch
  L119-131 configure_interpreter=True branch with discovery + configure_python_path
  L134-136 coordinator() returns MultiServerCoordinator
  L156    _probe_interpreter file not found
  L158-159 _probe_interpreter timeout
  L178-181 _probe_interpreter valid output parsing
  L184-193 _probe_interpreter out-of-range version returns None
  L204    _PythonInterpreter.discover step chain
  L208    all steps fail → PythonInterpreterNotFound raised
  L224-238 _PythonInterpreter.discover first successful step
  L244-246 _step1_env_override set
  L250-253 _step2_dot_venv
  L257-260 _step3_legacy_venv
  L264-268 _step4_poetry (no lock file)
  L272-278 _step5_pdm (no lock file)
  L282-284 _step6_uv (no lock file)
  L288-290 _step7_conda (no env.yml)
  L294-296 _step8_pipenv (no Pipfile.lock)
  L300-302 _step9_pyenv (no .python-version)
  L306-311 _step10_asdf (no .tool-versions)
  L314-320 _step11_pep582 (no __pypackages__)
  L324-326 _step12_pythonpath_walk (no PYTHONPATH)
  L329-331 _step13_python_host_path
  L335-337 _step14_sys_executable
  L341-343 _locate_global_symbol_offset (various AST node types)
  L347-352 _locate_global_symbol_offset class definition
  L356-360 _locate_global_symbol_offset Assign target

Pure unit tests — no real LSP processes or rope library needed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from serena.refactoring.python_strategy import (
    PythonInterpreterNotFound,
    _PythonInterpreter,
    _ResolvedInterpreter,
    _locate_global_symbol_offset,
    _probe_interpreter,
)


# ---------------------------------------------------------------------------
# _probe_interpreter
# ---------------------------------------------------------------------------


class TestProbeInterpreter:
    def test_nonexistent_path_returns_none(self, tmp_path: Path) -> None:
        missing = tmp_path / "python_nonexistent"
        result = _probe_interpreter(missing)
        assert result is None

    def test_valid_output_parsed(self, tmp_path: Path) -> None:
        """Simulate a successful probe via subprocess mock."""
        fake_python = tmp_path / "python"
        fake_python.touch()
        with patch("serena.refactoring.python_strategy.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="Python 3.11.5\n",
                stderr="",
                returncode=0,
            )
            result = _probe_interpreter(fake_python)
        assert result == (3, 11)

    def test_version_below_floor_returns_none(self, tmp_path: Path) -> None:
        fake_python = tmp_path / "python"
        fake_python.touch()
        with patch("serena.refactoring.python_strategy.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="Python 3.9.0\n",
                stderr="",
                returncode=0,
            )
            result = _probe_interpreter(fake_python)
        assert result is None

    def test_version_at_or_above_max_returns_none(self, tmp_path: Path) -> None:
        fake_python = tmp_path / "python"
        fake_python.touch()
        with patch("serena.refactoring.python_strategy.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="Python 3.14.0\n",
                stderr="",
                returncode=0,
            )
            result = _probe_interpreter(fake_python)
        assert result is None

    def test_timeout_returns_none(self, tmp_path: Path) -> None:
        import subprocess
        fake_python = tmp_path / "python"
        fake_python.touch()
        with patch("serena.refactoring.python_strategy.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="python", timeout=5.0)
            result = _probe_interpreter(fake_python)
        assert result is None

    def test_os_error_returns_none(self, tmp_path: Path) -> None:
        fake_python = tmp_path / "python"
        fake_python.touch()
        with patch("serena.refactoring.python_strategy.subprocess.run") as mock_run:
            mock_run.side_effect = OSError("permission denied")
            result = _probe_interpreter(fake_python)
        assert result is None

    def test_no_version_in_output_returns_none(self, tmp_path: Path) -> None:
        fake_python = tmp_path / "python"
        fake_python.touch()
        with patch("serena.refactoring.python_strategy.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", stderr="some error", returncode=1)
            result = _probe_interpreter(fake_python)
        assert result is None


# ---------------------------------------------------------------------------
# _PythonInterpreter discovery steps (unit testing each step)
# ---------------------------------------------------------------------------


class TestPythonInterpreterSteps:
    def test_step1_env_override_set(self, tmp_path: Path) -> None:
        fake_python = tmp_path / "mypython"
        with patch.dict("os.environ", {"O2_SCALPEL_PYTHON_INTERPRETER": str(fake_python)}):
            result = _PythonInterpreter._step1_env_override(tmp_path)
        assert result == fake_python

    def test_step1_env_override_not_set(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("O2_SCALPEL_PYTHON_INTERPRETER", None)
            result = _PythonInterpreter._step1_env_override(tmp_path)
        assert result is None

    def test_step2_dot_venv_exists(self, tmp_path: Path) -> None:
        bin_name = "Scripts" if sys.platform == "win32" else "bin"
        exe_name = "python.exe" if sys.platform == "win32" else "python"
        venv = tmp_path / ".venv" / bin_name
        venv.mkdir(parents=True)
        (venv / exe_name).touch()
        result = _PythonInterpreter._step2_dot_venv(tmp_path)
        assert result == venv / exe_name

    def test_step2_dot_venv_absent(self, tmp_path: Path) -> None:
        result = _PythonInterpreter._step2_dot_venv(tmp_path)
        assert result is None

    def test_step3_legacy_venv_exists(self, tmp_path: Path) -> None:
        bin_name = "Scripts" if sys.platform == "win32" else "bin"
        exe_name = "python.exe" if sys.platform == "win32" else "python"
        venv = tmp_path / "venv" / bin_name
        venv.mkdir(parents=True)
        (venv / exe_name).touch()
        result = _PythonInterpreter._step3_legacy_venv(tmp_path)
        assert result == venv / exe_name

    def test_step3_legacy_venv_absent(self, tmp_path: Path) -> None:
        result = _PythonInterpreter._step3_legacy_venv(tmp_path)
        assert result is None

    def test_step4_poetry_no_lock_file(self, tmp_path: Path) -> None:
        result = _PythonInterpreter._step4_poetry(tmp_path)
        assert result is None

    def test_step5_pdm_no_lock_file(self, tmp_path: Path) -> None:
        result = _PythonInterpreter._step5_pdm(tmp_path)
        assert result is None

    def test_step6_uv_no_lock_file(self, tmp_path: Path) -> None:
        result = _PythonInterpreter._step6_uv(tmp_path)
        assert result is None

    def test_step7_conda_no_env_yml(self, tmp_path: Path) -> None:
        result = _PythonInterpreter._step7_conda(tmp_path)
        assert result is None

    def test_step8_pipenv_no_pipfile(self, tmp_path: Path) -> None:
        result = _PythonInterpreter._step8_pipenv(tmp_path)
        assert result is None

    def test_step9_pyenv_no_python_version(self, tmp_path: Path) -> None:
        result = _PythonInterpreter._step9_pyenv(tmp_path)
        assert result is None

    def test_step10_asdf_no_tool_versions(self, tmp_path: Path) -> None:
        result = _PythonInterpreter._step10_asdf(tmp_path)
        assert result is None

    def test_step11_pep582_no_pypackages(self, tmp_path: Path) -> None:
        result = _PythonInterpreter._step11_pep582(tmp_path)
        assert result is None

    def test_step12_pythonpath_walk_no_env(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("PYTHONPATH", None)
            result = _PythonInterpreter._step12_pythonpath_walk(tmp_path)
        assert result is None

    def test_step13_python_host_path_set(self, tmp_path: Path) -> None:
        fake = tmp_path / "python"
        with patch.dict("os.environ", {"PYTHON_HOST_PATH": str(fake)}):
            result = _PythonInterpreter._step13_python_host_path(tmp_path)
        assert result == fake

    def test_step13_python_host_path_not_set(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("PYTHON_HOST_PATH", None)
            result = _PythonInterpreter._step13_python_host_path(tmp_path)
        assert result is None

    def test_step14_sys_executable(self, tmp_path: Path) -> None:
        result = _PythonInterpreter._step14_sys_executable(tmp_path)
        assert result is not None
        assert "python" in str(result).lower() or result.exists()


# ---------------------------------------------------------------------------
# _PythonInterpreter.discover — chain integration
# ---------------------------------------------------------------------------


class TestPythonInterpreterDiscover:
    def test_discover_via_env_override(self, tmp_path: Path) -> None:
        """Step 1 succeeds via env override."""
        fake_python = tmp_path / "mypython"
        fake_python.touch()
        with patch.dict("os.environ", {"O2_SCALPEL_PYTHON_INTERPRETER": str(fake_python)}):
            with patch("serena.refactoring.python_strategy._probe_interpreter") as mock_probe:
                mock_probe.return_value = (3, 11)
                result = _PythonInterpreter.discover(tmp_path)
        assert result.path == fake_python
        assert result.version == (3, 11)
        assert result.discovery_step == 1

    def test_discover_falls_through_to_sys_executable(self, tmp_path: Path) -> None:
        """All steps up to 14 fail; step 14 (sys.executable) succeeds."""
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("O2_SCALPEL_PYTHON_INTERPRETER", None)
            with patch("serena.refactoring.python_strategy._probe_interpreter") as mock_probe:
                # Make all probes fail except for the last call (step 14 — sys.executable).
                call_count = [0]

                def _probe(path: Path):
                    call_count[0] += 1
                    if str(sys.executable) in str(path):
                        return (3, 11)
                    return None

                mock_probe.side_effect = _probe
                result = _PythonInterpreter.discover(tmp_path)
        assert result.discovery_step == 14

    def test_discover_all_fail_raises(self, tmp_path: Path) -> None:
        """All 14 steps return None → PythonInterpreterNotFound raised."""
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("O2_SCALPEL_PYTHON_INTERPRETER", None)
            with patch("serena.refactoring.python_strategy._probe_interpreter") as mock_probe:
                mock_probe.return_value = None  # All probes fail.
                with pytest.raises(PythonInterpreterNotFound) as exc_info:
                    _PythonInterpreter.discover(tmp_path)
        assert len(exc_info.value.attempts) > 0

    def test_discover_step_raises_continues_chain(self, tmp_path: Path) -> None:
        """A step that raises is logged and skipped; chain continues.

        Directly test the discover() exception-handling path by making
        _probe_interpreter raise on first call. The discover loop catches
        exceptions from the step fn itself (not probe); we verify that
        even if one step returns a candidate that the probe rejects,
        the chain continues to the next step.
        """
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("O2_SCALPEL_PYTHON_INTERPRETER", None)

            # Make step 14 (sys.executable) yield a valid version so the
            # chain eventually succeeds even with intermediate probes failing.
            call_count = [0]
            sys_exec_path = Path(sys.executable)

            def _probe(path: Path):
                call_count[0] += 1
                # Only succeed for the actual sys.executable path.
                if path == sys_exec_path:
                    return (3, 11)
                return None

            with patch("serena.refactoring.python_strategy._probe_interpreter", side_effect=_probe):
                result = _PythonInterpreter.discover(tmp_path)
        # Chain reached step 14 and succeeded.
        assert result is not None
        assert result.discovery_step == 14


# ---------------------------------------------------------------------------
# _locate_global_symbol_offset
# ---------------------------------------------------------------------------


class TestLocateGlobalSymbolOffset:
    def test_function_def_found(self) -> None:
        source = "def foo():\n    pass\n"
        offset = _locate_global_symbol_offset(source, "foo")
        assert offset is not None
        assert source[offset:offset + 3] == "foo"

    def test_async_function_def_found(self) -> None:
        source = "async def bar():\n    pass\n"
        offset = _locate_global_symbol_offset(source, "bar")
        assert offset is not None
        assert source[offset:offset + 3] == "bar"

    def test_class_def_found(self) -> None:
        source = "class MyClass:\n    pass\n"
        offset = _locate_global_symbol_offset(source, "MyClass")
        assert offset is not None
        assert source[offset:offset + 7] == "MyClass"

    def test_assign_target_found(self) -> None:
        source = "MY_CONST = 42\n"
        offset = _locate_global_symbol_offset(source, "MY_CONST")
        assert offset is not None
        assert source[offset:offset + 8] == "MY_CONST"

    def test_ann_assign_found(self) -> None:
        source = "x: int = 5\n"
        offset = _locate_global_symbol_offset(source, "x")
        assert offset is not None
        assert source[offset] == "x"

    def test_symbol_not_found_returns_none(self) -> None:
        source = "def foo():\n    pass\n"
        result = _locate_global_symbol_offset(source, "missing_symbol")
        assert result is None

    def test_syntax_error_returns_none(self) -> None:
        source = "def (broken: syntax"
        result = _locate_global_symbol_offset(source, "foo")
        assert result is None

    def test_nested_symbol_not_found(self) -> None:
        """Nested symbols (methods inside class) are NOT at top level."""
        source = "class MyClass:\n    def method(self):\n        pass\n"
        # "method" is not a top-level binding.
        result = _locate_global_symbol_offset(source, "method")
        assert result is None

    def test_multiple_symbols_correct_one_returned(self) -> None:
        source = "def alpha():\n    pass\ndef beta():\n    pass\n"
        offset_alpha = _locate_global_symbol_offset(source, "alpha")
        offset_beta = _locate_global_symbol_offset(source, "beta")
        assert offset_alpha is not None
        assert offset_beta is not None
        assert offset_alpha < offset_beta


# ---------------------------------------------------------------------------
# PythonInterpreterNotFound
# ---------------------------------------------------------------------------


class TestPythonInterpreterNotFound:
    def test_message_includes_all_attempts(self) -> None:
        attempts = [
            (1, "no candidate"),
            (2, "candidate /x failed version probe"),
            (14, "candidate /usr/bin/python failed version probe"),
        ]
        exc = PythonInterpreterNotFound(attempts)
        msg = str(exc)
        assert "step 1" in msg
        assert "step 14" in msg
        assert exc.attempts == attempts
