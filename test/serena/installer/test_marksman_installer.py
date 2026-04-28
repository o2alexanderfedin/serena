"""v1.1.1 Leaf 03 C2 — :class:`MarksmanInstaller` tests.

Per the leaf README test environment block, marksman IS installed on
this host at ``/opt/homebrew/bin/marksman`` (version date 2026-02-08),
so :meth:`detect_installed` is exercised against the real binary on
macOS. The platform-branch tests exercise both branches by
monkeypatching :func:`platform.system` so the suite passes on Linux too.

The install/update tests mock :func:`subprocess.run` so the suite
never actually invokes ``brew install``.
"""

from __future__ import annotations

import platform
import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest

from serena.installer.marksman_installer import MarksmanInstaller


# -----------------------------------------------------------------------------
# detect_installed
# -----------------------------------------------------------------------------


def test_detect_installed_finds_marksman_on_this_host() -> None:
    """Per leaf README: marksman is at /opt/homebrew/bin/marksman on this host."""
    status = MarksmanInstaller().detect_installed()
    # Skip rather than fail when running on a host without marksman so
    # CI on a clean Linux VM stays green.
    if not status.present:
        pytest.skip("marksman not installed on this host; covered by mock tests")
    assert status.path is not None
    assert "marksman" in status.path
    assert status.version  # non-empty version string (date or semver)


def test_detect_installed_returns_absent_when_binary_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``shutil.which`` returns None, status.present must be False."""
    import serena.installer.marksman_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    status = MarksmanInstaller().detect_installed()
    assert status.present is False
    assert status.path is None
    assert status.version is None


# -----------------------------------------------------------------------------
# _install_command — per-platform branching
# -----------------------------------------------------------------------------


def test_install_command_on_macos_uses_brew(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    cmd = MarksmanInstaller()._install_command()  # pyright: ignore[reportPrivateUsage]
    assert cmd == ("brew", "install", "marksman")


def test_install_command_on_linux_uses_snap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    cmd = MarksmanInstaller()._install_command()  # pyright: ignore[reportPrivateUsage]
    assert cmd == ("snap", "install", "marksman")


def test_install_command_on_unknown_platform_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Plan9")
    with pytest.raises(NotImplementedError):
        MarksmanInstaller()._install_command()  # pyright: ignore[reportPrivateUsage]


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
    result = MarksmanInstaller().install(allow_install=False)
    assert result.dry_run is True
    assert result.success is False
    assert result.command_run == ("brew", "install", "marksman")
    assert result.return_code is None


def test_install_with_allow_install_true_invokes_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With explicit consent the install command is actually run."""
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    # Pretend brew is at a known path so the binary-resolution branch is exercised.
    import serena.installer.installer as installer_mod

    monkeypatch.setattr(
        installer_mod.shutil, "which",
        lambda name: f"/usr/local/bin/{name}" if name == "brew" else None,
    )

    captured: dict[str, Any] = {}

    def _fake_run(argv: list[str] | tuple[str, ...], **kwargs: Any) -> MagicMock:
        captured["argv"] = tuple(argv)
        captured["kwargs"] = kwargs
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = "==> Installing marksman\n"
        completed.stderr = ""
        return completed

    monkeypatch.setattr(installer_mod.subprocess, "run", _fake_run)
    result = MarksmanInstaller().install(allow_install=True)
    assert result.dry_run is False
    assert result.success is True
    assert result.return_code == 0
    assert result.stdout.startswith("==>")
    # Verb, not absolute path — but argv[0] is the resolved binary.
    assert captured["argv"][0] == "/usr/local/bin/brew"
    assert captured["argv"][1:] == ("install", "marksman")
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
    result = MarksmanInstaller().update(allow_update=True)
    assert result.dry_run is False
    assert result.success is True
    assert captured["argv"][1:] == ("install", "marksman")


# -----------------------------------------------------------------------------
# latest_available
# -----------------------------------------------------------------------------


def test_latest_available_returns_none_on_non_macos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    assert MarksmanInstaller().latest_available() is None


def test_latest_available_parses_brew_info_json_on_macos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    import serena.installer.marksman_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/brew")

    def _fake_run(argv: list[str] | tuple[str, ...], **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = (
            '[{"name":"marksman","versions":{"stable":"2026-02-08"}}]'
        )
        completed.stderr = ""
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    assert MarksmanInstaller().latest_available() == "2026-02-08"


def test_latest_available_returns_none_when_brew_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    import serena.installer.marksman_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/brew")

    def _raise(*_a: object, **_kw: object) -> None:
        raise subprocess.TimeoutExpired(cmd="brew", timeout=5.0)

    monkeypatch.setattr(mod.subprocess, "run", _raise)
    assert MarksmanInstaller().latest_available() is None


def test_latest_available_returns_none_when_brew_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    import serena.installer.marksman_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    assert MarksmanInstaller().latest_available() is None


# -----------------------------------------------------------------------------
# Class attributes
# -----------------------------------------------------------------------------


def test_class_attributes_match_spec() -> None:
    assert MarksmanInstaller.language == "markdown"
    assert MarksmanInstaller.binary_name == "marksman"
