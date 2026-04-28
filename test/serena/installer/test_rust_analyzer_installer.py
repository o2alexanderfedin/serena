"""v1.2 Leaf A — :class:`RustAnalyzerInstaller` tests.

Mirrors the marksman test layout: detection (real binary + monkeypatched
absent path), _install_command shape, and the inherited safety gate
(``allow_install=False`` MUST NOT touch :func:`subprocess.run`).
"""

from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest

from serena.installer.rust_analyzer_installer import RustAnalyzerInstaller


# -----------------------------------------------------------------------------
# detect_installed
# -----------------------------------------------------------------------------


def test_detect_installed_finds_rust_analyzer_when_on_path() -> None:
    """rust-analyzer is on PATH on hosts that ran ``rustup component add``."""
    status = RustAnalyzerInstaller().detect_installed()
    if not status.present:
        pytest.skip(
            "rust-analyzer not installed on this host; covered by mock tests",
        )
    assert status.path is not None
    assert "rust-analyzer" in status.path
    assert status.version
    # Version string is the raw `rust-analyzer X.Y.Z (sha date)` form.
    assert status.version.startswith("rust-analyzer ")


def test_detect_installed_returns_absent_when_binary_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import serena.installer.rust_analyzer_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    status = RustAnalyzerInstaller().detect_installed()
    assert status.present is False
    assert status.path is None
    assert status.version is None


def test_detect_installed_returns_no_version_when_probe_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-zero exit on --version → version=None, but present=True."""
    import serena.installer.rust_analyzer_installer as mod

    monkeypatch.setattr(
        mod.shutil, "which", lambda _name: "/fake/bin/rust-analyzer",
    )

    def _fake_run(_argv: object, **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 1
        completed.stdout = ""
        completed.stderr = "boom"
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    status = RustAnalyzerInstaller().detect_installed()
    assert status.present is True
    assert status.path == "/fake/bin/rust-analyzer"
    assert status.version is None


# -----------------------------------------------------------------------------
# _install_command — cross-platform (no platform branching)
# -----------------------------------------------------------------------------


def test_install_command_returns_rustup_argv() -> None:
    cmd = RustAnalyzerInstaller()._install_command()  # pyright: ignore[reportPrivateUsage]
    assert cmd == ("rustup", "component", "add", "rust-analyzer")


# -----------------------------------------------------------------------------
# latest_available — always None for toolchain-pinned components
# -----------------------------------------------------------------------------


def test_latest_available_always_returns_none() -> None:
    assert RustAnalyzerInstaller().latest_available() is None


# -----------------------------------------------------------------------------
# install / update — safety gate
# -----------------------------------------------------------------------------


def test_install_with_allow_install_false_does_not_invoke_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default safety: dry-run NEVER touches subprocess.run."""

    def _explode(*_a: object, **_kw: object) -> None:
        raise AssertionError("subprocess.run was invoked under allow_install=False")

    monkeypatch.setattr(subprocess, "run", _explode)
    result = RustAnalyzerInstaller().install(allow_install=False)
    assert result.dry_run is True
    assert result.success is False
    assert result.command_run == ("rustup", "component", "add", "rust-analyzer")
    assert result.return_code is None


def test_install_with_allow_install_true_invokes_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With explicit consent the install command is actually run."""
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
        completed.stdout = "info: component 'rust-analyzer' is up to date\n"
        completed.stderr = ""
        return completed

    monkeypatch.setattr(installer_mod.subprocess, "run", _fake_run)
    result = RustAnalyzerInstaller().install(allow_install=True)
    assert result.dry_run is False
    assert result.success is True
    assert result.return_code == 0
    assert captured["argv"][0] == "/usr/local/bin/rustup"
    assert captured["argv"][1:] == ("component", "add", "rust-analyzer")
    assert captured["kwargs"]["check"] is False


def test_update_with_allow_update_true_invokes_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """update() re-runs _install_command; same safety contract as install()."""
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
    result = RustAnalyzerInstaller().update(allow_update=True)
    assert result.dry_run is False
    assert result.success is True
    assert captured["argv"][1:] == ("component", "add", "rust-analyzer")


# -----------------------------------------------------------------------------
# Class attributes
# -----------------------------------------------------------------------------


def test_class_attributes_match_spec() -> None:
    assert RustAnalyzerInstaller.language == "rust"
    assert RustAnalyzerInstaller.binary_name == "rust-analyzer"
