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

import pytest


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


# ---------------------------------------------------------------------------
# stage-v0.2.0-review-m12 — pin the truthy-value contract.
#
# The plugin's activation predicate is the *exact* string ``"1"`` — no
# generic "truthy" interpretation. The two tests above cover the
# happy-path (``"1"``) and the unset case; this parametrized matrix pins
# that NO other plausible "yes-flavoured" value activates the plugin.
#
# If a future refactor relaxes the predicate to ``bool`` or ``int`` or a
# python truthy check (which would let ``"true"``, ``"yes"``, etc. through)
# this matrix fails loudly. The contract was chosen deliberately:
# string-equality is explicit, ASCII-stable across shells, and matches
# how the rest of the codebase treats opt-in env flags.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "flag_value",
    [
        pytest.param("true", id="lowercase-true"),
        pytest.param("yes", id="lowercase-yes"),
        pytest.param("0", id="zero"),
        pytest.param("", id="empty-string"),
        pytest.param("anything-else", id="arbitrary-string"),
    ],
)
def test_plugin_inactive_for_non_one_values(tmp_path: Path, flag_value: str) -> None:
    """ONLY exact ``"1"`` activates the plugin — no truthy-string interpretation.

    Regression cordon: a refactor that swaps the ``== "1"`` check for
    ``in {"1", "true", "yes"}`` or ``bool(value)`` would let any of these
    values through. This test fails first if that happens.
    """
    proc, out = _run_pytest(
        tmp_path, env_overrides={"O2_SCALPEL_LOCAL_HOST": flag_value}
    )
    assert proc.returncode == 0, (
        f"pytest failed for O2_SCALPEL_LOCAL_HOST={flag_value!r}:\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    assert out.read_text() == "__unset__", (
        f"plugin incorrectly activated for O2_SCALPEL_LOCAL_HOST={flag_value!r}; "
        f"only the literal string '1' must activate the shim"
    )
