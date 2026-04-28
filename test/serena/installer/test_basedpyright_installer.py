"""v1.2 Leaf A — :class:`BasedpyrightInstaller` tests."""

from __future__ import annotations

import json
import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest

from serena.installer.basedpyright_installer import BasedpyrightInstaller


# -----------------------------------------------------------------------------
# detect_installed
# -----------------------------------------------------------------------------


def test_detect_installed_finds_basedpyright_when_on_path() -> None:
    """basedpyright-langserver is on PATH on hosts that ran ``pipx install basedpyright``."""
    status = BasedpyrightInstaller().detect_installed()
    if not status.present:
        pytest.skip(
            "basedpyright not installed on this host; covered by mock tests",
        )
    assert status.path is not None
    assert "basedpyright-langserver" in status.path
    assert status.version


def test_detect_installed_returns_absent_when_binary_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.basedpyright_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    status = BasedpyrightInstaller().detect_installed()
    assert status.present is False
    assert status.path is None
    assert status.version is None


def test_detect_installed_returns_no_version_when_probe_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.basedpyright_installer as mod

    monkeypatch.setattr(
        mod.shutil, "which", lambda _name: "/fake/bin/basedpyright-langserver",
    )

    def _fake_run(_argv: object, **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 1
        completed.stdout = ""
        completed.stderr = "boom"
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    status = BasedpyrightInstaller().detect_installed()
    assert status.present is True
    assert status.version is None


# -----------------------------------------------------------------------------
# _install_command
# -----------------------------------------------------------------------------


def test_install_command_returns_pipx_argv() -> None:
    cmd = BasedpyrightInstaller()._install_command()  # pyright: ignore[reportPrivateUsage]
    assert cmd == ("pipx", "install", "basedpyright")


# -----------------------------------------------------------------------------
# latest_available
# -----------------------------------------------------------------------------


def test_latest_available_returns_none_when_pipx_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.basedpyright_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    assert BasedpyrightInstaller().latest_available() is None


def test_latest_available_parses_pipx_list_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.basedpyright_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/pipx")

    payload = {
        "venvs": {
            "basedpyright": {
                "metadata": {
                    "main_package": {"package_version": "1.31.0"},
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
    assert BasedpyrightInstaller().latest_available() == "1.31.0"


def test_latest_available_returns_none_on_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.basedpyright_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/pipx")

    def _raise(*_a: object, **_kw: object) -> None:
        raise subprocess.TimeoutExpired(cmd="pipx", timeout=5.0)

    monkeypatch.setattr(mod.subprocess, "run", _raise)
    assert BasedpyrightInstaller().latest_available() is None


# -----------------------------------------------------------------------------
# install / update — safety gate
# -----------------------------------------------------------------------------


def test_install_with_allow_install_false_does_not_invoke_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _explode(*_a: object, **_kw: object) -> None:
        raise AssertionError("subprocess.run was invoked under allow_install=False")

    monkeypatch.setattr(subprocess, "run", _explode)
    result = BasedpyrightInstaller().install(allow_install=False)
    assert result.dry_run is True
    assert result.success is False
    assert result.command_run == ("pipx", "install", "basedpyright")
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
        completed.stdout = "  installed package basedpyright 1.31.0\n"
        completed.stderr = ""
        return completed

    monkeypatch.setattr(installer_mod.subprocess, "run", _fake_run)
    result = BasedpyrightInstaller().install(allow_install=True)
    assert result.dry_run is False
    assert result.success is True
    assert result.return_code == 0
    assert captured["argv"][0] == "/usr/local/bin/pipx"
    assert captured["argv"][1:] == ("install", "basedpyright")
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
    result = BasedpyrightInstaller().update(allow_update=True)
    assert result.dry_run is False
    assert result.success is True
    assert captured["argv"][1:] == ("install", "basedpyright")


# -----------------------------------------------------------------------------
# Class attributes
# -----------------------------------------------------------------------------


def test_class_attributes_match_spec() -> None:
    assert BasedpyrightInstaller.language == "python-basedpyright"
    assert BasedpyrightInstaller.binary_name == "basedpyright-langserver"
