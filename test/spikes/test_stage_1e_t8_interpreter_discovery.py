"""T8 — 14-step Python interpreter discovery (specialist-python.md §7)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


def _write_fake_python(path: Path, version: str = "3.11.7") -> None:
    """Create an executable shell stub that echoes ``Python <version>``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/usr/bin/env bash\necho 'Python {version}'\n")
    path.chmod(0o755)


# ---- Step 1: O2_SCALPEL_PYTHON_INTERPRETER env override ----------------

def test_step1_env_override_wins(tmp_path: Path) -> None:
    from serena.refactoring.python_strategy import _PythonInterpreter

    fake = tmp_path / "fake-python"
    _write_fake_python(fake)
    with patch.dict(os.environ, {"O2_SCALPEL_PYTHON_INTERPRETER": str(fake)}, clear=False):
        resolved = _PythonInterpreter.discover(tmp_path)
        assert resolved.path == fake
        assert resolved.version == (3, 11)
        assert resolved.discovery_step == 1


# ---- Step 2: project .venv ---------------------------------------------

def test_step2_dot_venv_in_project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from serena.refactoring.python_strategy import _PythonInterpreter

    monkeypatch.delenv("O2_SCALPEL_PYTHON_INTERPRETER", raising=False)
    py = tmp_path / ".venv" / "bin" / "python"
    _write_fake_python(py, "3.12.1")
    resolved = _PythonInterpreter.discover(tmp_path)
    assert resolved.path == py
    assert resolved.discovery_step == 2


# ---- Step 14: sys.executable fallback ----------------------------------

def test_step14_sys_executable_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from serena.refactoring.python_strategy import _PythonInterpreter

    for v in (
        "O2_SCALPEL_PYTHON_INTERPRETER",
        "PYTHONPATH",
        "PYTHON_HOST_PATH",
        "CONDA_DEFAULT_ENV",
    ):
        monkeypatch.delenv(v, raising=False)
    resolved = _PythonInterpreter.discover(tmp_path)
    assert resolved.path == Path(sys.executable)
    assert resolved.discovery_step == 14


# ---- Version-floor enforcement (Phase 0 P3): reject < 3.10 -------------

def test_resolver_rejects_python_3_9(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from serena.refactoring.python_strategy import (
        PythonInterpreterNotFound,
        _PythonInterpreter,
    )

    monkeypatch.delenv("O2_SCALPEL_PYTHON_INTERPRETER", raising=False)
    fake = tmp_path / ".venv" / "bin" / "python"
    _write_fake_python(fake, "3.9.18")
    with patch.object(sys, "executable", str(fake)):
        with pytest.raises(PythonInterpreterNotFound):
            _PythonInterpreter.discover(tmp_path)


# ---- Step 4: Poetry detection (mock subprocess) ------------------------

def test_step4_poetry_env_info(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from serena.refactoring import python_strategy
    from serena.refactoring.python_strategy import _PythonInterpreter

    monkeypatch.delenv("O2_SCALPEL_PYTHON_INTERPRETER", raising=False)
    (tmp_path / "poetry.lock").write_text("# stub\n")
    fake = tmp_path / "poetry-venv" / "bin" / "python"
    _write_fake_python(fake, "3.11.0")

    real_run = subprocess.run

    def fake_run(cmd, *a, **kw):  # type: ignore[no-untyped-def]
        if isinstance(cmd, list) and cmd[:3] == ["poetry", "env", "info"]:
            class R:
                stdout = str(fake.parent.parent) + "\n"
                returncode = 0
                stderr = ""
            return R()
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(python_strategy.subprocess, "run", fake_run)
    monkeypatch.setattr(python_strategy.shutil, "which", lambda name: "/usr/bin/" + name)
    resolved = _PythonInterpreter.discover(tmp_path)
    assert resolved.discovery_step == 4
    assert resolved.path == fake


# ---- Step 5: PDM detection (mock subprocess) ---------------------------

def test_step5_pdm_info(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from serena.refactoring import python_strategy
    from serena.refactoring.python_strategy import _PythonInterpreter

    monkeypatch.delenv("O2_SCALPEL_PYTHON_INTERPRETER", raising=False)
    (tmp_path / "pdm.lock").write_text("# stub\n")
    fake = tmp_path / "pdm-venv" / "bin" / "python"
    _write_fake_python(fake, "3.12.4")

    real_run = subprocess.run

    def fake_run(cmd, *a, **kw):  # type: ignore[no-untyped-def]
        if isinstance(cmd, list) and cmd[:2] == ["pdm", "info"]:
            class R:
                stdout = str(fake) + "\n"
                returncode = 0
                stderr = ""
            return R()
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(python_strategy.subprocess, "run", fake_run)
    monkeypatch.setattr(python_strategy.shutil, "which", lambda name: "/usr/bin/" + name)
    resolved = _PythonInterpreter.discover(tmp_path)
    assert resolved.discovery_step == 5
    assert resolved.path == fake


# ---- Step 6: uv detection (mock subprocess) ----------------------------

def test_step6_uv_python_find(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from serena.refactoring import python_strategy
    from serena.refactoring.python_strategy import _PythonInterpreter

    monkeypatch.delenv("O2_SCALPEL_PYTHON_INTERPRETER", raising=False)
    (tmp_path / "uv.lock").write_text("# stub\n")
    fake = tmp_path / "uv-venv" / "bin" / "python"
    _write_fake_python(fake, "3.13.0")

    real_run = subprocess.run

    def fake_run(cmd, *a, **kw):  # type: ignore[no-untyped-def]
        if isinstance(cmd, list) and cmd[:3] == ["uv", "python", "find"]:
            class R:
                stdout = str(fake) + "\n"
                returncode = 0
                stderr = ""
            return R()
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(python_strategy.subprocess, "run", fake_run)
    monkeypatch.setattr(python_strategy.shutil, "which", lambda name: "/usr/bin/" + name)
    resolved = _PythonInterpreter.discover(tmp_path)
    assert resolved.discovery_step == 6
    assert resolved.path == fake


# ---- Step 7: conda detection (mock subprocess) -------------------------

def test_step7_conda_envs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from serena.refactoring import python_strategy
    from serena.refactoring.python_strategy import _PythonInterpreter

    monkeypatch.delenv("O2_SCALPEL_PYTHON_INTERPRETER", raising=False)
    (tmp_path / "environment.yml").write_text("name: scalpel\n")
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "scalpel")
    env_root = tmp_path / "conda-envs" / "scalpel"
    fake = env_root / "bin" / "python"
    _write_fake_python(fake, "3.11.6")

    real_run = subprocess.run

    def fake_run(cmd, *a, **kw):  # type: ignore[no-untyped-def]
        if isinstance(cmd, list) and cmd[:2] == ["conda", "info"]:
            class R:
                stdout = f"# conda environments:\nscalpel  *  {env_root}\n"
                returncode = 0
                stderr = ""
            return R()
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(python_strategy.subprocess, "run", fake_run)
    monkeypatch.setattr(python_strategy.shutil, "which", lambda name: "/usr/bin/" + name)
    resolved = _PythonInterpreter.discover(tmp_path)
    assert resolved.discovery_step == 7
    assert resolved.path == fake


# ---- Step 8: pipenv detection (mock subprocess) ------------------------

def test_step8_pipenv_py(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from serena.refactoring import python_strategy
    from serena.refactoring.python_strategy import _PythonInterpreter

    monkeypatch.delenv("O2_SCALPEL_PYTHON_INTERPRETER", raising=False)
    (tmp_path / "Pipfile.lock").write_text("# stub\n")
    fake = tmp_path / "pipenv-venv" / "bin" / "python"
    _write_fake_python(fake, "3.10.13")

    real_run = subprocess.run

    def fake_run(cmd, *a, **kw):  # type: ignore[no-untyped-def]
        if isinstance(cmd, list) and cmd[:2] == ["pipenv", "--py"]:
            class R:
                stdout = str(fake) + "\n"
                returncode = 0
                stderr = ""
            return R()
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(python_strategy.subprocess, "run", fake_run)
    monkeypatch.setattr(python_strategy.shutil, "which", lambda name: "/usr/bin/" + name)
    resolved = _PythonInterpreter.discover(tmp_path)
    assert resolved.discovery_step == 8
    assert resolved.path == fake


# ---- Step 9: pyenv detection (mock subprocess) -------------------------

def test_step9_pyenv_which(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from serena.refactoring import python_strategy
    from serena.refactoring.python_strategy import _PythonInterpreter

    monkeypatch.delenv("O2_SCALPEL_PYTHON_INTERPRETER", raising=False)
    (tmp_path / ".python-version").write_text("3.12.2\n")
    fake = tmp_path / "pyenv-shim" / "python"
    _write_fake_python(fake, "3.12.2")

    real_run = subprocess.run

    def fake_run(cmd, *a, **kw):  # type: ignore[no-untyped-def]
        if isinstance(cmd, list) and cmd[:2] == ["pyenv", "which"]:
            class R:
                stdout = str(fake) + "\n"
                returncode = 0
                stderr = ""
            return R()
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(python_strategy.subprocess, "run", fake_run)
    monkeypatch.setattr(python_strategy.shutil, "which", lambda name: "/usr/bin/" + name)
    resolved = _PythonInterpreter.discover(tmp_path)
    assert resolved.discovery_step == 9
    assert resolved.path == fake


# ---- Step 10: asdf detection (mock subprocess) -------------------------

def test_step10_asdf_where(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from serena.refactoring import python_strategy
    from serena.refactoring.python_strategy import _PythonInterpreter

    monkeypatch.delenv("O2_SCALPEL_PYTHON_INTERPRETER", raising=False)
    (tmp_path / ".tool-versions").write_text("python 3.11.4\nnodejs 20.0.0\n")
    asdf_root = tmp_path / "asdf-install" / "python-3.11.4"
    fake = asdf_root / "bin" / "python"
    _write_fake_python(fake, "3.11.4")

    real_run = subprocess.run

    def fake_run(cmd, *a, **kw):  # type: ignore[no-untyped-def]
        if isinstance(cmd, list) and cmd[:2] == ["asdf", "where"]:
            class R:
                stdout = str(asdf_root) + "\n"
                returncode = 0
                stderr = ""
            return R()
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(python_strategy.subprocess, "run", fake_run)
    monkeypatch.setattr(python_strategy.shutil, "which", lambda name: "/usr/bin/" + name)
    resolved = _PythonInterpreter.discover(tmp_path)
    assert resolved.discovery_step == 10
    assert resolved.path == fake


# ---- Step 11: PEP 582 __pypackages__ -----------------------------------

def test_step11_pep582_pypackages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from serena.refactoring import python_strategy
    from serena.refactoring.python_strategy import _PythonInterpreter

    monkeypatch.delenv("O2_SCALPEL_PYTHON_INTERPRETER", raising=False)
    (tmp_path / "__pypackages__" / "3.11" / "lib").mkdir(parents=True)
    fake = tmp_path / "system-py" / "python3.11"
    _write_fake_python(fake, "3.11.9")

    def fake_which(name: str) -> str | None:
        if name == "python3.11":
            return str(fake)
        return None

    monkeypatch.setattr(python_strategy.shutil, "which", fake_which)
    resolved = _PythonInterpreter.discover(tmp_path)
    assert resolved.discovery_step == 11
    assert resolved.path == fake


# ---- Step 12: PYTHONPATH walk + dist-info ------------------------------

def test_step12_pythonpath_dist_info(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from serena.refactoring import python_strategy
    from serena.refactoring.python_strategy import _PythonInterpreter

    monkeypatch.delenv("O2_SCALPEL_PYTHON_INTERPRETER", raising=False)
    site = tmp_path / "site-packages"
    (site / "somepkg-1.0.dist-info").mkdir(parents=True)
    (site / "somepkg-1.0.dist-info" / "METADATA").write_text("Metadata-Version: 2.1\n")
    monkeypatch.setenv("PYTHONPATH", str(site))
    fake = tmp_path / "system-py" / "python3"
    _write_fake_python(fake, "3.12.0")

    def fake_which(name: str) -> str | None:
        if name in ("python3", "python"):
            return str(fake)
        return None

    monkeypatch.setattr(python_strategy.shutil, "which", fake_which)
    resolved = _PythonInterpreter.discover(tmp_path)
    assert resolved.discovery_step == 12
    assert resolved.path == fake


# ---- Step 13: PYTHON_HOST_PATH env override ----------------------------

def test_step13_python_host_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from serena.refactoring.python_strategy import _PythonInterpreter

    monkeypatch.delenv("O2_SCALPEL_PYTHON_INTERPRETER", raising=False)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    fake = tmp_path / "host-py" / "python"
    _write_fake_python(fake, "3.13.1")
    monkeypatch.setenv("PYTHON_HOST_PATH", str(fake))
    resolved = _PythonInterpreter.discover(tmp_path)
    assert resolved.discovery_step == 13
    assert resolved.path == fake
