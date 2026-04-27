"""Tests for the developer-host opt-in pytest plugin.

These tests verify the opt-in semantics of ``conftest_dev_host``:

* By default (no ``O2_SCALPEL_LOCAL_HOST`` env var), the plugin must NOT
  set ``CARGO_BUILD_RUSTC`` — so CI hosts inherit a clean environment.
* With ``O2_SCALPEL_LOCAL_HOST=1``, the plugin must export
  ``CARGO_BUILD_RUSTC=rustc`` — neutralising the developer's broken
  ``rust-fv-driver`` cargo wrapper.

See ``docs/dev/host-rustc-shim.md`` for context.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path


def _run_pytest(
    tmp_path: Path,
    env_overrides: dict[str, str],
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run a child pytest that records the value of ``CARGO_BUILD_RUSTC``.

    The child process loads the ``test.conftest_dev_host`` plugin
    explicitly via ``-p test.conftest_dev_host`` (in the parent test
    suite the same plugin is auto-loaded via ``pytest_plugins`` in this
    project's root ``conftest.py``; the child runs in an isolated
    ``tmp_path`` with no conftest of its own, so it must register the
    plugin by hand). The fixture file simply writes the live
    environment value to ``_O2_OUT`` for the parent to assert on.
    """
    test_file = tmp_path / "test_dummy.py"
    test_file.write_text(
        textwrap.dedent(
            """
            import os


            def test_env() -> None:
                with open(os.environ["_O2_OUT"], "w", encoding="utf-8") as f:
                    f.write(os.environ.get("CARGO_BUILD_RUSTC", "__unset__"))
            """
        ).lstrip()
    )
    out = tmp_path / "out.txt"
    env = {**os.environ, "_O2_OUT": str(out), **env_overrides}
    env.pop("CARGO_BUILD_RUSTC", None)
    if "O2_SCALPEL_LOCAL_HOST" not in env_overrides:
        env.pop("O2_SCALPEL_LOCAL_HOST", None)
    # Run with the serena package directory on sys.path so the
    # ``test.conftest_dev_host`` plugin is importable. The child runs
    # in an isolated ``tmp_path`` cwd with no ``conftest.py`` of its
    # own, so the parent project's ``pytest_plugins`` declaration is
    # NOT inherited — we register the plugin explicitly via ``-p`` so
    # the child loads the same code path under test.
    serena_root = Path(__file__).resolve().parents[1]
    child_env = {**env, "PYTHONPATH": str(serena_root)}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "test.conftest_dev_host",
            str(test_file),
            "-q",
        ],
        capture_output=True,
        text=True,
        env=child_env,
        cwd=tmp_path,
        check=False,
    )
    return proc, out


def test_plugin_inactive_without_env_var(tmp_path: Path) -> None:
    """Without the opt-in flag the plugin must leave CARGO_BUILD_RUSTC unset."""
    proc, out = _run_pytest(tmp_path, env_overrides={})
    assert proc.returncode == 0, f"pytest failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    assert out.read_text() == "__unset__"


def test_plugin_active_when_local_host_flag_set(tmp_path: Path) -> None:
    """With ``O2_SCALPEL_LOCAL_HOST=1`` the plugin must export ``CARGO_BUILD_RUSTC=rustc``."""
    proc, out = _run_pytest(tmp_path, env_overrides={"O2_SCALPEL_LOCAL_HOST": "1"})
    assert proc.returncode == 0, f"pytest failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    assert out.read_text() == "rustc"
