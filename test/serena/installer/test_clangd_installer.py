"""Stream 6 / Leaf C — :class:`ClangdInstaller` tests.

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

from serena.installer.clangd_installer import ClangdInstaller


# -----------------------------------------------------------------------------
# detect_installed
# -----------------------------------------------------------------------------


def test_detect_installed_returns_absent_when_binary_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``shutil.which`` returns None, status.present must be False."""
    import serena.installer.clangd_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    status = ClangdInstaller().detect_installed()
    assert status.present is False
    assert status.path is None
    assert status.version is None


def test_detect_installed_returns_present_when_binary_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``shutil.which`` returns a path, status.present must be True."""
    import serena.installer.clangd_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/bin/clangd")

    def _fake_run(argv: tuple, **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = "clangd version 18.1.3\nFeatures: ...\n"
        completed.stderr = ""
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    status = ClangdInstaller().detect_installed()
    assert status.present is True
    assert status.path == "/usr/bin/clangd"
    assert status.version == "18.1.3"


# -----------------------------------------------------------------------------
# _install_command — per-platform branching
# -----------------------------------------------------------------------------


def test_install_command_on_macos_uses_brew_llvm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    cmd = ClangdInstaller()._install_command()  # pyright: ignore[reportPrivateUsage]
    assert cmd == ("brew", "install", "llvm")


def test_install_command_on_linux_uses_snap_clangd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    cmd = ClangdInstaller()._install_command()  # pyright: ignore[reportPrivateUsage]
    assert cmd == ("snap", "install", "clangd", "--classic")


def test_install_command_on_unknown_platform_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Plan9")
    with pytest.raises(NotImplementedError):
        ClangdInstaller()._install_command()  # pyright: ignore[reportPrivateUsage]


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
    result = ClangdInstaller().install(allow_install=False)
    assert result.dry_run is True
    assert result.success is False
    assert result.command_run == ("brew", "install", "llvm")
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
        completed.stdout = "==> Installing llvm\n"
        completed.stderr = ""
        return completed

    monkeypatch.setattr(installer_mod.subprocess, "run", _fake_run)
    result = ClangdInstaller().install(allow_install=True)
    assert result.dry_run is False
    assert result.success is True
    assert result.return_code == 0
    assert captured["argv"][0] == "/usr/local/bin/brew"
    assert captured["argv"][1:] == ("install", "llvm")
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
    result = ClangdInstaller().update(allow_update=True)
    assert result.dry_run is False
    assert result.success is True
    assert captured["argv"][1:] == ("install", "llvm")


# -----------------------------------------------------------------------------
# latest_available
# -----------------------------------------------------------------------------


def test_latest_available_returns_none_on_non_macos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    assert ClangdInstaller().latest_available() is None


def test_latest_available_parses_brew_info_json_on_macos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    import serena.installer.clangd_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/brew")

    def _fake_run(argv: list[str] | tuple[str, ...], **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = (
            '[{"name":"llvm","versions":{"stable":"18.1.3"}}]'
        )
        completed.stderr = ""
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    assert ClangdInstaller().latest_available() == "18.1.3"


def test_latest_available_returns_none_when_brew_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    import serena.installer.clangd_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/brew")

    def _raise(*_a: object, **_kw: object) -> None:
        raise subprocess.TimeoutExpired(cmd="brew", timeout=5.0)

    monkeypatch.setattr(mod.subprocess, "run", _raise)
    assert ClangdInstaller().latest_available() is None


def test_latest_available_returns_none_when_brew_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    import serena.installer.clangd_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    assert ClangdInstaller().latest_available() is None


def test_latest_available_returns_none_when_brew_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    import serena.installer.clangd_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/brew")

    def _fake_run(argv: list[str] | tuple[str, ...], **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 1
        completed.stdout = ""
        completed.stderr = "Error: No formulae found\n"
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    assert ClangdInstaller().latest_available() is None


# -----------------------------------------------------------------------------
# Class attributes
# -----------------------------------------------------------------------------


def test_class_attributes_match_spec() -> None:
    assert ClangdInstaller.language == "cpp"
    assert ClangdInstaller.binary_name == "clangd"
    assert ClangdInstaller.brew_formula == "llvm"
