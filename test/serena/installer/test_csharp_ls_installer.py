"""Stream 6 / Leaf I — :class:`CsharpLsInstaller` tests.

These tests exercise the installer's install-command shape, safety gate,
and version-probe logic without making real network calls or touching the
filesystem. ``subprocess.run`` is always monkeypatched so the suite is
fully offline.

The installer is cross-platform (macOS, Linux, Windows all use the same
``dotnet tool install --global csharp-ls`` command), so we verify the
dotnet-absent guard instead of per-platform branching.

The class attributes test at the bottom asserts the stable API contract
that ``InstallLspServersTool`` relies on when it walks the installer
registry.
"""

from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest

from serena.installer.csharp_ls_installer import CsharpLsInstaller


# -----------------------------------------------------------------------------
# detect_installed
# -----------------------------------------------------------------------------


def test_detect_installed_returns_absent_when_binary_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``shutil.which`` returns None, status.present must be False."""
    import serena.installer.csharp_ls_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    status = CsharpLsInstaller().detect_installed()
    assert status.present is False
    assert status.path is None
    assert status.version is None


def test_detect_installed_returns_present_when_binary_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``shutil.which`` returns a path, status.present must be True."""
    import serena.installer.csharp_ls_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/home/user/.dotnet/tools/csharp-ls")

    def _fake_run(argv: tuple, **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = "0.14.0+e5a1b23\n"
        completed.stderr = ""
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    status = CsharpLsInstaller().detect_installed()
    assert status.present is True
    assert status.path == "/home/user/.dotnet/tools/csharp-ls"
    assert status.version == "0.14.0+e5a1b23"


def test_detect_installed_returns_present_with_plain_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Version without commit suffix (e.g. '0.14.0') should be parsed correctly."""
    import serena.installer.csharp_ls_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/csharp-ls")

    def _fake_run(argv: tuple, **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = "0.14.0\n"
        completed.stderr = ""
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    status = CsharpLsInstaller().detect_installed()
    assert status.present is True
    assert status.version == "0.14.0"


# -----------------------------------------------------------------------------
# _install_command — dotnet presence check
# -----------------------------------------------------------------------------


def test_install_command_uses_dotnet_tool_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When dotnet is on PATH, the install command must be the global tool install."""
    import serena.installer.csharp_ls_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda name: f"/usr/local/bin/{name}" if name == "dotnet" else None)
    cmd = CsharpLsInstaller()._install_command()  # pyright: ignore[reportPrivateUsage]
    assert cmd == ("/usr/local/bin/dotnet", "tool", "install", "--global", "csharp-ls")


def test_install_command_raises_when_dotnet_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When dotnet is absent, _install_command raises NotImplementedError."""
    import serena.installer.csharp_ls_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    with pytest.raises(NotImplementedError, match="dotnet"):
        CsharpLsInstaller()._install_command()  # pyright: ignore[reportPrivateUsage]


# -----------------------------------------------------------------------------
# install — safety gate
# -----------------------------------------------------------------------------


def test_install_with_allow_install_false_does_not_invoke_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default safety: dry-run NEVER touches subprocess.run."""
    import serena.installer.csharp_ls_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda name: f"/usr/local/bin/{name}" if name == "dotnet" else None)

    def _explode(*_a: object, **_kw: object) -> None:
        raise AssertionError("subprocess.run was invoked under allow_install=False")

    monkeypatch.setattr(subprocess, "run", _explode)
    result = CsharpLsInstaller().install(allow_install=False)
    assert result.dry_run is True
    assert result.success is False
    assert result.command_run == ("/usr/local/bin/dotnet", "tool", "install", "--global", "csharp-ls")
    assert result.return_code is None


def test_install_with_allow_install_true_invokes_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With explicit consent the install command is actually run."""
    import serena.installer.csharp_ls_installer as mod
    import serena.installer.installer as installer_mod

    monkeypatch.setattr(mod.shutil, "which", lambda name: f"/usr/local/bin/{name}" if name == "dotnet" else None)
    monkeypatch.setattr(
        installer_mod.shutil,
        "which",
        lambda name: f"/usr/local/bin/{name}" if name == "dotnet" else None,
    )

    captured: dict[str, Any] = {}

    def _fake_run(argv: list[str] | tuple[str, ...], **kwargs: Any) -> MagicMock:
        captured["argv"] = tuple(argv)
        captured["kwargs"] = kwargs
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = "Tool 'csharp-ls' was successfully installed.\n"
        completed.stderr = ""
        return completed

    monkeypatch.setattr(installer_mod.subprocess, "run", _fake_run)
    result = CsharpLsInstaller().install(allow_install=True)
    assert result.dry_run is False
    assert result.success is True
    assert result.return_code == 0
    assert captured["argv"][0] == "/usr/local/bin/dotnet"
    assert captured["argv"][1:] == ("tool", "install", "--global", "csharp-ls")
    assert captured["kwargs"]["check"] is False


def test_update_with_allow_update_true_invokes_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """update() re-runs _install_command; safety gate identical to install()."""
    import serena.installer.csharp_ls_installer as mod
    import serena.installer.installer as installer_mod

    monkeypatch.setattr(mod.shutil, "which", lambda name: f"/usr/local/bin/{name}" if name == "dotnet" else None)
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
    result = CsharpLsInstaller().update(allow_update=True)
    assert result.dry_run is False
    assert result.success is True
    assert captured["argv"][1:] == ("tool", "install", "--global", "csharp-ls")


# -----------------------------------------------------------------------------
# latest_available
# -----------------------------------------------------------------------------


def test_latest_available_returns_none_when_dotnet_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When dotnet is absent, latest_available returns None."""
    import serena.installer.csharp_ls_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    assert CsharpLsInstaller().latest_available() is None


def test_latest_available_parses_dotnet_tool_search_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """latest_available must extract the version from ``dotnet tool search`` output."""
    import serena.installer.csharp_ls_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/dotnet")

    def _fake_run(argv: list[str] | tuple[str, ...], **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = (
            "Package ID      Latest Version  Authors          \n"
            "---------------------------------------------------\n"
            "csharp-ls       0.14.0          razzmatazz       \n"
        )
        completed.stderr = ""
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    assert CsharpLsInstaller().latest_available() == "0.14.0"


def test_latest_available_returns_none_when_dotnet_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.csharp_ls_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/dotnet")

    def _raise(*_a: object, **_kw: object) -> None:
        raise subprocess.TimeoutExpired(cmd="dotnet", timeout=10.0)

    monkeypatch.setattr(mod.subprocess, "run", _raise)
    assert CsharpLsInstaller().latest_available() is None


def test_latest_available_returns_none_when_dotnet_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.csharp_ls_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/dotnet")

    def _fake_run(argv: list[str] | tuple[str, ...], **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 1
        completed.stdout = ""
        completed.stderr = "Error: command failed\n"
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    assert CsharpLsInstaller().latest_available() is None


def test_latest_available_returns_none_on_unparseable_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the search output has no recognizable version line, return None."""
    import serena.installer.csharp_ls_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/dotnet")

    def _fake_run(argv: list[str] | tuple[str, ...], **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = "No packages found\n"
        completed.stderr = ""
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    assert CsharpLsInstaller().latest_available() is None


# -----------------------------------------------------------------------------
# Class attributes
# -----------------------------------------------------------------------------


def test_class_attributes_match_spec() -> None:
    assert CsharpLsInstaller.language == "csharp"
    assert CsharpLsInstaller.binary_name == "csharp-ls"
