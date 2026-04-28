"""Stream 6 / Leaf E — :class:`LeanInstaller` tests.

These tests exercise the installer's install-command shape, safety gate,
and version-probe logic without making real network calls or touching
the filesystem. ``subprocess.run`` is always monkeypatched so the suite
is fully offline.

elan (the Lean toolchain manager) is the bootstrap mechanism. Unlike
brew/snap/cargo, the first install requires a curl-then-bash bootstrap
that we explicitly refuse to auto-execute — the installer raises
``NotImplementedError`` when elan is absent to surface the bootstrap
instructions to the user.  These tests verify that behaviour.

The class attributes test at the bottom asserts the stable API contract
that ``ScalpelInstallLspServersTool`` relies on when it walks the installer
registry.
"""

from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest

from serena.installer.lean_installer import LeanInstaller, _extract_elan_stable_version


# -----------------------------------------------------------------------------
# detect_installed
# -----------------------------------------------------------------------------


def test_detect_installed_returns_absent_when_binary_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``shutil.which`` returns None, status.present must be False."""
    import serena.installer.lean_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    status = LeanInstaller().detect_installed()
    assert status.present is False
    assert status.path is None
    assert status.version is None


def test_detect_installed_returns_present_when_binary_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``shutil.which`` returns a path, status.present must be True."""
    import serena.installer.lean_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/local/bin/lean")

    def _fake_run(argv: tuple, **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = "Lean (version 4.14.0, commit abc1234, Release)\n"
        completed.stderr = ""
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    status = LeanInstaller().detect_installed()
    assert status.present is True
    assert status.path == "/usr/local/bin/lean"
    assert status.version == "4.14.0"


def test_detect_installed_parses_version_from_stderr_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Some lean builds print version info to stderr; both are checked."""
    import serena.installer.lean_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/opt/lean/bin/lean")

    def _fake_run(argv: tuple, **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = ""
        completed.stderr = "Lean (version 4.12.0, ...)\n"
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    status = LeanInstaller().detect_installed()
    assert status.present is True
    assert status.version == "4.12.0"


# -----------------------------------------------------------------------------
# _install_command — elan-based install
# -----------------------------------------------------------------------------


def test_install_command_uses_elan_when_elan_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When elan is on PATH, the command delegates to elan toolchain install stable."""
    import serena.installer.lean_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda name: f"/usr/local/bin/{name}" if name == "elan" else None)
    cmd = LeanInstaller()._install_command()  # pyright: ignore[reportPrivateUsage]
    assert cmd == ("/usr/local/bin/elan", "toolchain", "install", "stable")


def test_install_command_raises_when_elan_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When elan is absent, NotImplementedError is raised with bootstrap instructions."""
    import serena.installer.lean_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    with pytest.raises(NotImplementedError, match="elan"):
        LeanInstaller()._install_command()  # pyright: ignore[reportPrivateUsage]


def test_install_command_error_message_contains_bootstrap_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The error message must contain the elan bootstrap URL."""
    import serena.installer.lean_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    with pytest.raises(NotImplementedError) as exc_info:
        LeanInstaller()._install_command()  # pyright: ignore[reportPrivateUsage]
    assert "elan-init.sh" in str(exc_info.value)


# -----------------------------------------------------------------------------
# install — safety gate
# -----------------------------------------------------------------------------


def test_install_with_allow_install_false_does_not_invoke_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default safety: dry-run NEVER touches subprocess.run."""
    import serena.installer.lean_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda name: f"/usr/local/bin/{name}" if name == "elan" else None)

    def _explode(*_a: object, **_kw: object) -> None:
        raise AssertionError("subprocess.run was invoked under allow_install=False")

    monkeypatch.setattr(subprocess, "run", _explode)
    result = LeanInstaller().install(allow_install=False)
    assert result.dry_run is True
    assert result.success is False
    assert result.command_run == ("/usr/local/bin/elan", "toolchain", "install", "stable")
    assert result.return_code is None


def test_install_with_allow_install_true_invokes_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With explicit consent the install command is actually run."""
    import serena.installer.installer as installer_mod
    import serena.installer.lean_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda name: f"/usr/local/bin/{name}" if name == "elan" else None)
    monkeypatch.setattr(
        installer_mod.shutil,
        "which",
        lambda name: f"/usr/local/bin/{name}" if name == "elan" else None,
    )

    captured: dict[str, Any] = {}

    def _fake_run(argv: list[str] | tuple[str, ...], **kwargs: Any) -> MagicMock:
        captured["argv"] = tuple(argv)
        captured["kwargs"] = kwargs
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = "info: installed toolchain 'stable'\n"
        completed.stderr = ""
        return completed

    monkeypatch.setattr(installer_mod.subprocess, "run", _fake_run)
    result = LeanInstaller().install(allow_install=True)
    assert result.dry_run is False
    assert result.success is True
    assert result.return_code == 0
    assert captured["argv"][0] == "/usr/local/bin/elan"
    assert captured["argv"][1:] == ("toolchain", "install", "stable")
    assert captured["kwargs"]["check"] is False


def test_update_with_allow_update_true_invokes_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """update() re-runs _install_command; safety gate identical to install()."""
    import serena.installer.installer as installer_mod
    import serena.installer.lean_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda name: f"/x/{name}" if name == "elan" else None)
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
    result = LeanInstaller().update(allow_update=True)
    assert result.dry_run is False
    assert result.success is True
    assert captured["argv"][1:] == ("toolchain", "install", "stable")


# -----------------------------------------------------------------------------
# latest_available — elan toolchain list
# -----------------------------------------------------------------------------


def test_latest_available_returns_none_when_elan_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When elan is not on PATH, latest_available returns None gracefully."""
    import serena.installer.lean_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    assert LeanInstaller().latest_available() is None


def test_latest_available_parses_elan_toolchain_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """latest_available() extracts the highest concrete version from elan output."""
    import serena.installer.lean_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/local/bin/elan" if name == "elan" else None)

    def _fake_run(argv: tuple, **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = (
            "leanprover/lean4:stable (default)\n"
            "leanprover/lean4:v4.12.0\n"
            "leanprover/lean4:v4.14.0\n"
        )
        completed.stderr = ""
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    assert LeanInstaller().latest_available() == "4.14.0"


def test_latest_available_returns_none_when_elan_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.lean_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/local/bin/elan" if name == "elan" else None)

    def _raise(*_a: object, **_kw: object) -> None:
        raise subprocess.TimeoutExpired(cmd="elan", timeout=5.0)

    monkeypatch.setattr(mod.subprocess, "run", _raise)
    assert LeanInstaller().latest_available() is None


def test_latest_available_returns_none_when_elan_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.lean_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/local/bin/elan" if name == "elan" else None)

    def _fake_run(argv: tuple, **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 1
        completed.stdout = ""
        completed.stderr = "error: elan not initialized\n"
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    assert LeanInstaller().latest_available() is None


# -----------------------------------------------------------------------------
# _extract_elan_stable_version (unit tests for the parsing helper)
# -----------------------------------------------------------------------------


def test_extract_elan_stable_version_picks_highest() -> None:
    """Highest semver is returned when multiple versions are installed."""
    output = (
        "leanprover/lean4:stable (default)\n"
        "leanprover/lean4:v4.12.0\n"
        "leanprover/lean4:v4.14.0\n"
        "leanprover/lean4:v4.13.1\n"
    )
    assert _extract_elan_stable_version(output) == "4.14.0"


def test_extract_elan_stable_version_returns_none_on_empty_output() -> None:
    assert _extract_elan_stable_version("") is None


def test_extract_elan_stable_version_returns_none_on_no_versioned_toolchains() -> None:
    """Only symbolic 'stable' present — no concrete version to extract."""
    output = "leanprover/lean4:stable (default)\n"
    assert _extract_elan_stable_version(output) is None


def test_extract_elan_stable_version_handles_single_version() -> None:
    output = "leanprover/lean4:v4.14.0\n"
    assert _extract_elan_stable_version(output) == "4.14.0"


# -----------------------------------------------------------------------------
# Class attributes
# -----------------------------------------------------------------------------


def test_class_attributes_match_spec() -> None:
    assert LeanInstaller.language == "lean"
    assert LeanInstaller.binary_name == "lean"
