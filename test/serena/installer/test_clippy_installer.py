"""v1.2 Leaf A — :class:`ClippyInstaller` tests."""

from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest

from serena.installer.clippy_installer import ClippyInstaller


# -----------------------------------------------------------------------------
# detect_installed
# -----------------------------------------------------------------------------


def test_detect_installed_finds_cargo_clippy_when_on_path() -> None:
    """cargo-clippy is on PATH on hosts that ran ``rustup component add clippy``."""
    status = ClippyInstaller().detect_installed()
    if not status.present:
        pytest.skip("clippy not installed on this host; covered by mock tests")
    assert status.path is not None
    assert "cargo-clippy" in status.path
    assert status.version
    # `cargo-clippy --version` prints `clippy 0.1.95 (sha date)`.
    assert status.version.startswith("clippy ")


def test_detect_installed_returns_absent_when_binary_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.clippy_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    status = ClippyInstaller().detect_installed()
    assert status.present is False
    assert status.path is None
    assert status.version is None


def test_detect_installed_returns_no_version_when_probe_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.clippy_installer as mod

    monkeypatch.setattr(
        mod.shutil, "which", lambda _name: "/fake/bin/cargo-clippy",
    )

    def _fake_run(_argv: object, **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 1
        completed.stdout = ""
        completed.stderr = "boom"
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    status = ClippyInstaller().detect_installed()
    assert status.present is True
    assert status.path == "/fake/bin/cargo-clippy"
    assert status.version is None


# -----------------------------------------------------------------------------
# install_command
# -----------------------------------------------------------------------------


def test_install_command_returns_rustup_argv() -> None:
    cmd = ClippyInstaller().install_command()
    assert cmd == ("rustup", "component", "add", "clippy")


# -----------------------------------------------------------------------------
# latest_available
# -----------------------------------------------------------------------------


def test_latest_available_always_returns_none() -> None:
    assert ClippyInstaller().latest_available() is None


# -----------------------------------------------------------------------------
# install / update — safety gate
# -----------------------------------------------------------------------------


def test_install_with_allow_install_false_does_not_invoke_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _explode(*_a: object, **_kw: object) -> None:
        raise AssertionError("subprocess.run was invoked under allow_install=False")

    monkeypatch.setattr(subprocess, "run", _explode)
    result = ClippyInstaller().install(allow_install=False)
    assert result.dry_run is True
    assert result.success is False
    assert result.command_run == ("rustup", "component", "add", "clippy")
    assert result.return_code is None


def test_install_with_allow_install_true_invokes_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.installer as installer_mod

    monkeypatch.setattr(
        installer_mod.shutil, "which",
        lambda name: f"/usr/local/bin/{name}" if name == "rustup" else None,
    )

    captured: dict[str, Any] = {}

    def _fake_run(argv: list[str] | tuple[str, ...], **kwargs: Any) -> MagicMock:
        captured["argv"] = tuple(argv)
        captured["kwargs"] = kwargs
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = "info: component 'clippy' is up to date\n"
        completed.stderr = ""
        return completed

    monkeypatch.setattr(installer_mod.subprocess, "run", _fake_run)
    result = ClippyInstaller().install(allow_install=True)
    assert result.dry_run is False
    assert result.success is True
    assert result.return_code == 0
    assert captured["argv"][0] == "/usr/local/bin/rustup"
    assert captured["argv"][1:] == ("component", "add", "clippy")
    assert captured["kwargs"]["check"] is False


def test_update_with_allow_update_true_invokes_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    result = ClippyInstaller().update(allow_update=True)
    assert result.dry_run is False
    assert result.success is True
    assert captured["argv"][1:] == ("component", "add", "clippy")


# -----------------------------------------------------------------------------
# Class attributes
# -----------------------------------------------------------------------------


def test_class_attributes_match_spec() -> None:
    assert ClippyInstaller.language == "rust-clippy"
    assert ClippyInstaller.binary_name == "cargo-clippy"
