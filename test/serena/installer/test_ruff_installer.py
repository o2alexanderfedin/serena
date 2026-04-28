"""v1.2 Leaf A — :class:`RuffInstaller` tests."""

from __future__ import annotations

import json
import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest

from serena.installer.ruff_installer import RuffInstaller


# -----------------------------------------------------------------------------
# detect_installed
# -----------------------------------------------------------------------------


def test_detect_installed_finds_ruff_when_on_path() -> None:
    """ruff is on PATH on hosts that ran ``pipx install ruff``."""
    status = RuffInstaller().detect_installed()
    if not status.present:
        pytest.skip("ruff not installed on this host; covered by mock tests")
    assert status.path is not None
    assert "ruff" in status.path
    assert status.version
    assert status.version.startswith("ruff ")


def test_detect_installed_returns_absent_when_binary_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.ruff_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    status = RuffInstaller().detect_installed()
    assert status.present is False
    assert status.path is None
    assert status.version is None


def test_detect_installed_returns_no_version_when_probe_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.ruff_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/fake/bin/ruff")

    def _fake_run(_argv: object, **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 2
        completed.stdout = ""
        completed.stderr = "boom"
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    status = RuffInstaller().detect_installed()
    assert status.present is True
    assert status.version is None


# -----------------------------------------------------------------------------
# _install_command
# -----------------------------------------------------------------------------


def test_install_command_returns_pipx_argv() -> None:
    cmd = RuffInstaller()._install_command()  # pyright: ignore[reportPrivateUsage]
    assert cmd == ("pipx", "install", "ruff")


# -----------------------------------------------------------------------------
# latest_available
# -----------------------------------------------------------------------------


def test_latest_available_returns_none_when_pipx_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.ruff_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    assert RuffInstaller().latest_available() is None


def test_latest_available_returns_none_when_pipx_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.ruff_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/pipx")

    def _raise(*_a: object, **_kw: object) -> None:
        raise subprocess.TimeoutExpired(cmd="pipx", timeout=5.0)

    monkeypatch.setattr(mod.subprocess, "run", _raise)
    assert RuffInstaller().latest_available() is None


def test_latest_available_parses_pipx_list_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.ruff_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/pipx")

    payload = {
        "venvs": {
            "ruff": {
                "metadata": {
                    "main_package": {"package_version": "0.14.6"},
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
    assert RuffInstaller().latest_available() == "0.14.6"


def test_latest_available_returns_none_when_package_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.ruff_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/pipx")

    def _fake_run(_argv: object, **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = json.dumps({"venvs": {}})
        completed.stderr = ""
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    assert RuffInstaller().latest_available() is None


# -----------------------------------------------------------------------------
# install / update — safety gate
# -----------------------------------------------------------------------------


def test_install_with_allow_install_false_does_not_invoke_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _explode(*_a: object, **_kw: object) -> None:
        raise AssertionError("subprocess.run was invoked under allow_install=False")

    monkeypatch.setattr(subprocess, "run", _explode)
    result = RuffInstaller().install(allow_install=False)
    assert result.dry_run is True
    assert result.success is False
    assert result.command_run == ("pipx", "install", "ruff")
    assert result.return_code is None


def test_install_with_allow_install_true_invokes_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.installer as installer_mod

    monkeypatch.setattr(
        installer_mod.shutil, "which",
        lambda name: f"/usr/local/bin/{name}" if name == "pipx" else None,
    )

    captured: dict[str, Any] = {}

    def _fake_run(argv: list[str] | tuple[str, ...], **kwargs: Any) -> MagicMock:
        captured["argv"] = tuple(argv)
        captured["kwargs"] = kwargs
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = "  installed package ruff 0.14.6\n"
        completed.stderr = ""
        return completed

    monkeypatch.setattr(installer_mod.subprocess, "run", _fake_run)
    result = RuffInstaller().install(allow_install=True)
    assert result.dry_run is False
    assert result.success is True
    assert result.return_code == 0
    assert captured["argv"][0] == "/usr/local/bin/pipx"
    assert captured["argv"][1:] == ("install", "ruff")
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
    result = RuffInstaller().update(allow_update=True)
    assert result.dry_run is False
    assert result.success is True
    assert captured["argv"][1:] == ("install", "ruff")


# -----------------------------------------------------------------------------
# Class attributes
# -----------------------------------------------------------------------------


def test_class_attributes_match_spec() -> None:
    assert RuffInstaller.language == "python-ruff"
    assert RuffInstaller.binary_name == "ruff"
