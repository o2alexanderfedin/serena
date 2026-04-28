"""v1.2 Leaf A — :class:`PylspInstaller` tests.

The pylsp installer is the most exotic of the v1.2 set: it has a
TWO-step install flow (``pipx install python-lsp-server`` THEN
``pipx inject python-lsp-server pylsp-rope``). The safety gate must
hold for BOTH steps — neither subprocess.run call may fire under
``allow_install=False``.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest

from serena.installer.pylsp_installer import PylspInstaller


# -----------------------------------------------------------------------------
# detect_installed
# -----------------------------------------------------------------------------


def test_detect_installed_finds_pylsp_when_on_path() -> None:
    status = PylspInstaller().detect_installed()
    if not status.present:
        pytest.skip("pylsp not installed on this host; covered by mock tests")
    assert status.path is not None
    assert "pylsp" in status.path
    assert status.version


def test_detect_installed_returns_absent_when_binary_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.pylsp_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    status = PylspInstaller().detect_installed()
    assert status.present is False
    assert status.path is None
    assert status.version is None


def test_detect_installed_falls_back_to_stderr_for_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pylsp prints version on stderr in some builds; both branches must be covered."""
    import serena.installer.pylsp_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/fake/bin/pylsp")

    def _fake_run(_argv: object, **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = ""
        completed.stderr = "pylsp v1.13.1\n"
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    status = PylspInstaller().detect_installed()
    assert status.present is True
    assert status.version == "pylsp v1.13.1"


# -----------------------------------------------------------------------------
# install_command
# -----------------------------------------------------------------------------


def test_install_command_returns_pipx_install_argv() -> None:
    cmd = PylspInstaller().install_command()
    assert cmd == ("pipx", "install", "python-lsp-server")


def test_inject_command_class_attribute() -> None:
    """The pylsp-rope inject argv is exposed for the dry-run preview."""
    assert PylspInstaller.inject_command == (
        "pipx", "inject", "python-lsp-server", "pylsp-rope",
    )


# -----------------------------------------------------------------------------
# latest_available
# -----------------------------------------------------------------------------


def test_latest_available_returns_none_when_pipx_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.pylsp_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    assert PylspInstaller().latest_available() is None


def test_latest_available_parses_pipx_list_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.pylsp_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/pipx")

    payload = {
        "venvs": {
            "python-lsp-server": {
                "metadata": {
                    "main_package": {"package_version": "1.13.1"},
                },
            },
        },
    }

    def _fake_run(_argv: object, **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = json.dumps(payload)
        completed.stderr = ""
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    assert PylspInstaller().latest_available() == "1.13.1"


# -----------------------------------------------------------------------------
# install — safety gate covers BOTH steps
# -----------------------------------------------------------------------------


def test_install_with_allow_install_false_does_not_invoke_either_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default safety: dry-run NEVER touches subprocess.run, even for the inject step."""
    fired: list[tuple[str, ...]] = []

    def _track(argv: list[str] | tuple[str, ...], **_kw: Any) -> None:
        fired.append(tuple(argv))
        raise AssertionError(f"subprocess.run invoked under allow_install=False: {argv!r}")

    monkeypatch.setattr(subprocess, "run", _track)
    result = PylspInstaller().install(allow_install=False)
    assert result.dry_run is True
    assert result.success is False
    # The dry-run preview surfaces the PRIMARY install argv; the inject
    # argv is exposed via PylspInstaller.inject_command for callers that
    # want to render both steps.
    assert result.command_run == ("pipx", "install", "python-lsp-server")
    assert result.return_code is None
    assert fired == []


def test_install_with_allow_install_true_invokes_both_install_and_inject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With explicit consent both pipx install AND pipx inject fire."""
    import serena.installer.installer as installer_mod
    import serena.installer.pylsp_installer as pylsp_mod

    monkeypatch.setattr(
        installer_mod.shutil, "which",
        lambda name: f"/usr/local/bin/{name}" if name == "pipx" else None,
    )
    monkeypatch.setattr(
        pylsp_mod.shutil, "which",
        lambda name: f"/usr/local/bin/{name}" if name == "pipx" else None,
    )

    captured: list[tuple[str, ...]] = []

    def _fake_run(argv: list[str] | tuple[str, ...], **_kw: Any) -> MagicMock:
        captured.append(tuple(argv))
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        if "inject" in argv:
            completed.stdout = "  injected package pylsp-rope into venv python-lsp-server\n"
        else:
            completed.stdout = "  installed package python-lsp-server 1.13.1\n"
        completed.stderr = ""
        return completed

    monkeypatch.setattr(installer_mod.subprocess, "run", _fake_run)
    monkeypatch.setattr(pylsp_mod.subprocess, "run", _fake_run)

    result = PylspInstaller().install(allow_install=True)
    assert result.dry_run is False
    assert result.success is True
    assert result.return_code == 0
    # Two subprocess invocations: primary install, then pylsp-rope inject.
    assert len(captured) == 2
    assert captured[0][0] == "/usr/local/bin/pipx"
    assert captured[0][1:] == ("install", "python-lsp-server")
    assert captured[1][0] == "/usr/local/bin/pipx"
    assert captured[1][1:] == ("inject", "python-lsp-server", "pylsp-rope")
    # Final command_run reflects the inject step (the last invocation).
    assert result.command_run[1:] == ("inject", "python-lsp-server", "pylsp-rope")
    # stdout merges both step outputs so the LLM sees the full picture.
    assert "installed package python-lsp-server" in result.stdout
    assert "injected package pylsp-rope" in result.stdout


def test_install_skips_inject_when_primary_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If pipx install fails, the inject step MUST NOT fire."""
    import serena.installer.installer as installer_mod
    import serena.installer.pylsp_installer as pylsp_mod

    monkeypatch.setattr(
        installer_mod.shutil, "which",
        lambda name: f"/usr/local/bin/{name}" if name == "pipx" else None,
    )
    monkeypatch.setattr(
        pylsp_mod.shutil, "which",
        lambda name: f"/usr/local/bin/{name}" if name == "pipx" else None,
    )

    captured: list[tuple[str, ...]] = []

    def _fake_run(argv: list[str] | tuple[str, ...], **_kw: Any) -> MagicMock:
        captured.append(tuple(argv))
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 1  # primary install failed
        completed.stdout = ""
        completed.stderr = "pipx: package python-lsp-server not found\n"
        return completed

    monkeypatch.setattr(installer_mod.subprocess, "run", _fake_run)
    # Inject step should never be reached, but if a regression fires it
    # we want the test to fail loudly instead of silently passing.
    monkeypatch.setattr(pylsp_mod.subprocess, "run", _fake_run)

    result = PylspInstaller().install(allow_install=True)
    assert result.success is False
    assert result.dry_run is False
    # Only the primary install ran; the inject step was suppressed.
    assert len(captured) == 1
    assert captured[0][1:] == ("install", "python-lsp-server")


def test_update_with_allow_update_true_runs_both_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.installer as installer_mod
    import serena.installer.pylsp_installer as pylsp_mod

    monkeypatch.setattr(installer_mod.shutil, "which", lambda name: f"/x/{name}")
    monkeypatch.setattr(pylsp_mod.shutil, "which", lambda name: f"/x/{name}")

    captured: list[tuple[str, ...]] = []

    def _fake_run(argv: list[str] | tuple[str, ...], **_kw: Any) -> MagicMock:
        captured.append(tuple(argv))
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = ""
        completed.stderr = ""
        return completed

    monkeypatch.setattr(installer_mod.subprocess, "run", _fake_run)
    monkeypatch.setattr(pylsp_mod.subprocess, "run", _fake_run)

    result = PylspInstaller().update(allow_update=True)
    assert result.dry_run is False
    assert result.success is True
    assert len(captured) == 2
    assert captured[0][1:] == ("install", "python-lsp-server")
    assert captured[1][1:] == ("inject", "python-lsp-server", "pylsp-rope")


def test_update_with_allow_update_false_does_not_invoke_either_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _explode(*_a: object, **_kw: object) -> None:
        raise AssertionError("subprocess.run invoked under allow_update=False")

    monkeypatch.setattr(subprocess, "run", _explode)
    result = PylspInstaller().update(allow_update=False)
    assert result.dry_run is True
    assert result.success is False
    assert result.command_run == ("pipx", "install", "python-lsp-server")


# -----------------------------------------------------------------------------
# Class attributes
# -----------------------------------------------------------------------------


def test_class_attributes_match_spec() -> None:
    assert PylspInstaller.language == "python"
    assert PylspInstaller.binary_name == "pylsp"
