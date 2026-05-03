"""Stream 6 / Leaf D — :class:`JdtlsInstaller` tests.

These tests exercise the installer's platform-branching install-command
shape, safety gate, and version-probe logic without making real network
calls or touching the filesystem. ``subprocess.run`` is always
monkeypatched so the suite is fully offline.

The platform-branch tests exercise both Darwin and Linux branches by
monkeypatching :func:`platform.system` so the suite passes on any host OS.

The class attributes test at the bottom asserts the stable API contract
that ``InstallLspServersTool`` relies on when it walks the installer
registry.
"""

from __future__ import annotations

import platform
import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest

from serena.installer.jdtls_installer import JdtlsInstaller


# -----------------------------------------------------------------------------
# detect_installed
# -----------------------------------------------------------------------------


def test_detect_installed_returns_absent_when_binary_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``shutil.which`` returns None, status.present must be False."""
    import serena.installer.jdtls_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    status = JdtlsInstaller().detect_installed()
    assert status.present is False
    assert status.path is None
    assert status.version is None


def test_detect_installed_returns_present_when_binary_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``shutil.which`` returns a path, status.present must be True."""
    import serena.installer.jdtls_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/jdtls")

    def _fake_run(argv: tuple, **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = "jdtls 1.38.0\n"
        completed.stderr = ""
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    status = JdtlsInstaller().detect_installed()
    assert status.present is True
    assert status.path == "/usr/local/bin/jdtls"
    assert status.version == "1.38.0"


# -----------------------------------------------------------------------------
# _install_command — per-platform branching
# -----------------------------------------------------------------------------


def test_install_command_on_macos_uses_brew_jdtls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    cmd = JdtlsInstaller()._install_command()  # pyright: ignore[reportPrivateUsage]
    assert cmd == ("brew", "install", "jdtls")


def test_install_command_on_linux_uses_snap_jdtls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    cmd = JdtlsInstaller()._install_command()  # pyright: ignore[reportPrivateUsage]
    assert cmd == ("snap", "install", "jdtls", "--classic")


def test_install_command_on_unknown_platform_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Plan9")
    with pytest.raises(NotImplementedError):
        JdtlsInstaller()._install_command()  # pyright: ignore[reportPrivateUsage]


# -----------------------------------------------------------------------------
# install — safety gate
# -----------------------------------------------------------------------------


def test_install_with_allow_install_false_does_not_invoke_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default safety: dry-run NEVER touches subprocess.run."""
    monkeypatch.setattr(platform, "system", lambda: "Darwin")

    def _explode(*_a: object, **_kw: object) -> None:
        raise AssertionError("subprocess.run was invoked under allow_install=False")

    monkeypatch.setattr(subprocess, "run", _explode)
    result = JdtlsInstaller().install(allow_install=False)
    assert result.dry_run is True
    assert result.success is False
    assert result.command_run == ("brew", "install", "jdtls")
    assert result.return_code is None


def test_install_with_allow_install_true_invokes_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With explicit consent the install command is actually run."""
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    import serena.installer.installer as installer_mod

    monkeypatch.setattr(
        installer_mod.shutil,
        "which",
        lambda name: f"/usr/local/bin/{name}" if name == "brew" else None,
    )

    captured: dict[str, Any] = {}

    def _fake_run(argv: list[str] | tuple[str, ...], **kwargs: Any) -> MagicMock:
        captured["argv"] = tuple(argv)
        captured["kwargs"] = kwargs
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = "==> Installing jdtls\n"
        completed.stderr = ""
        return completed

    monkeypatch.setattr(installer_mod.subprocess, "run", _fake_run)
    result = JdtlsInstaller().install(allow_install=True)
    assert result.dry_run is False
    assert result.success is True
    assert result.return_code == 0
    assert captured["argv"][0] == "/usr/local/bin/brew"
    assert captured["argv"][1:] == ("install", "jdtls")
    assert captured["kwargs"]["check"] is False


def test_update_with_allow_update_true_invokes_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """update() re-runs _install_command; safety gate identical to install()."""
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
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
    result = JdtlsInstaller().update(allow_update=True)
    assert result.dry_run is False
    assert result.success is True
    assert captured["argv"][1:] == ("install", "jdtls")


# -----------------------------------------------------------------------------
# latest_available
# -----------------------------------------------------------------------------


def test_latest_available_returns_none_on_non_macos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    assert JdtlsInstaller().latest_available() is None


def test_latest_available_parses_brew_info_json_on_macos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    import serena.installer.jdtls_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/brew")

    def _fake_run(argv: list[str] | tuple[str, ...], **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = (
            '[{"name":"jdtls","versions":{"stable":"1.38.0"}}]'
        )
        completed.stderr = ""
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    assert JdtlsInstaller().latest_available() == "1.38.0"


def test_latest_available_returns_none_when_brew_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    import serena.installer.jdtls_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/brew")

    def _raise(*_a: object, **_kw: object) -> None:
        raise subprocess.TimeoutExpired(cmd="brew", timeout=5.0)

    monkeypatch.setattr(mod.subprocess, "run", _raise)
    assert JdtlsInstaller().latest_available() is None


def test_latest_available_returns_none_when_brew_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    import serena.installer.jdtls_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    assert JdtlsInstaller().latest_available() is None


def test_latest_available_returns_none_when_brew_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    import serena.installer.jdtls_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/brew")

    def _fake_run(argv: list[str] | tuple[str, ...], **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 1
        completed.stdout = ""
        completed.stderr = "Error: No formulae found\n"
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    assert JdtlsInstaller().latest_available() is None


# -----------------------------------------------------------------------------
# Class attributes
# -----------------------------------------------------------------------------


def test_class_attributes_match_spec() -> None:
    assert JdtlsInstaller.language == "java"
    assert JdtlsInstaller.binary_name == "jdtls"
    assert JdtlsInstaller.brew_formula == "jdtls"
