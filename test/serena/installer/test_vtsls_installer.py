"""Stream 6 / Leaf A — :class:`VtslsInstaller` tests.

These tests exercise the installer's npm-command shape, safety gate, and
version-probe logic without making real network calls or touching the
filesystem. ``subprocess.run`` is always monkeypatched so the suite is
fully offline.

The class attributes test at the bottom asserts the stable API contract
that ``ScalpelInstallLspServersTool`` relies on when it walks the
installer registry.
"""

from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest

from serena.installer.vtsls_installer import VtslsInstaller


# -----------------------------------------------------------------------------
# detect_installed
# -----------------------------------------------------------------------------


def test_detect_installed_returns_absent_when_binary_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``shutil.which`` returns None, status.present must be False."""
    import serena.installer.vtsls_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    status = VtslsInstaller().detect_installed()
    assert status.present is False
    assert status.path is None
    assert status.version is None


def test_detect_installed_returns_present_when_binary_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``shutil.which`` returns a path, status.present must be True."""
    import serena.installer.vtsls_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/vtsls")

    def _fake_run(argv: tuple, **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = "0.2.9\n"
        completed.stderr = ""
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    status = VtslsInstaller().detect_installed()
    assert status.present is True
    assert status.path == "/usr/local/bin/vtsls"
    assert status.version == "0.2.9"


# -----------------------------------------------------------------------------
# _install_command — cross-platform (npm, no branching)
# -----------------------------------------------------------------------------


def test_install_command_uses_npm_global_install() -> None:
    """npm is cross-platform; install command must be the same on all OSes."""
    cmd = VtslsInstaller()._install_command()  # pyright: ignore[reportPrivateUsage]
    assert cmd == ("npm", "install", "-g", "@vtsls/language-server")


# -----------------------------------------------------------------------------
# install — safety gate
# -----------------------------------------------------------------------------


def test_install_with_allow_install_false_does_not_invoke_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default safety: dry-run NEVER touches subprocess.run."""

    def _explode(*_a: object, **_kw: object) -> None:
        raise AssertionError("subprocess.run was invoked under allow_install=False")

    monkeypatch.setattr(subprocess, "run", _explode)
    result = VtslsInstaller().install(allow_install=False)
    assert result.dry_run is True
    assert result.success is False
    assert result.command_run == ("npm", "install", "-g", "@vtsls/language-server")
    assert result.return_code is None


def test_install_with_allow_install_true_invokes_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With explicit consent the install command is actually run."""
    import serena.installer.installer as installer_mod

    monkeypatch.setattr(
        installer_mod.shutil,
        "which",
        lambda name: f"/usr/local/bin/{name}" if name == "npm" else None,
    )

    captured: dict[str, Any] = {}

    def _fake_run(argv: list[str] | tuple[str, ...], **kwargs: Any) -> MagicMock:
        captured["argv"] = tuple(argv)
        captured["kwargs"] = kwargs
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = "added 1 package\n"
        completed.stderr = ""
        return completed

    monkeypatch.setattr(installer_mod.subprocess, "run", _fake_run)
    result = VtslsInstaller().install(allow_install=True)
    assert result.dry_run is False
    assert result.success is True
    assert result.return_code == 0
    assert captured["argv"][0] == "/usr/local/bin/npm"
    assert captured["argv"][1:] == ("install", "-g", "@vtsls/language-server")
    assert captured["kwargs"]["check"] is False


def test_update_with_allow_update_true_invokes_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """update() re-runs _install_command; safety gate identical to install()."""
    import serena.installer.installer as installer_mod

    monkeypatch.setattr(installer_mod.shutil, "which", lambda name: f"/x/{name}")

    captured: dict[str, Any] = {}

    def _fake_run(argv: list[str] | tuple[str, ...], **_kw: Any) -> MagicMock:
        captured["argv"] = tuple(argv)
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = ""
        completed.stderr = ""
        return completed

    monkeypatch.setattr(installer_mod.subprocess, "run", _fake_run)
    result = VtslsInstaller().update(allow_update=True)
    assert result.dry_run is False
    assert result.success is True
    assert captured["argv"][1:] == ("install", "-g", "@vtsls/language-server")


# -----------------------------------------------------------------------------
# latest_available
# -----------------------------------------------------------------------------


def test_latest_available_returns_none_when_npm_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.vtsls_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    assert VtslsInstaller().latest_available() is None


def test_latest_available_parses_npm_view_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.vtsls_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/npm")

    def _fake_run(argv: tuple, **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = "0.2.9\n"
        completed.stderr = ""
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    assert VtslsInstaller().latest_available() == "0.2.9"


def test_latest_available_returns_none_when_npm_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.vtsls_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/npm")

    def _raise(*_a: object, **_kw: object) -> None:
        raise subprocess.TimeoutExpired(cmd="npm", timeout=10.0)

    monkeypatch.setattr(mod.subprocess, "run", _raise)
    assert VtslsInstaller().latest_available() is None


def test_latest_available_returns_none_when_npm_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.vtsls_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/npm")

    def _fake_run(argv: tuple, **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 1
        completed.stdout = ""
        completed.stderr = "npm ERR!\n"
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    assert VtslsInstaller().latest_available() is None


# -----------------------------------------------------------------------------
# Class attributes
# -----------------------------------------------------------------------------


def test_class_attributes_match_spec() -> None:
    assert VtslsInstaller.language == "typescript"
    assert VtslsInstaller.binary_name == "vtsls"
    assert VtslsInstaller.npm_package == "@vtsls/language-server"
