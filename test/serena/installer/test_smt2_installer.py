"""v1.4.1 Leaf B — :class:`Smt2Installer` tests.

Smt2Installer downloads the pre-built ``dolmenls`` binary from the
``Gbury/dolmen`` GitHub Releases (pinned to v0.10) and drops it on
``~/.local/bin``. The install command is a single ``sh -c`` chain
(``mkdir -p ... && curl ... && chmod +x ...``) so it fits the
:class:`LspInstaller._install_command` single-argv contract.

Tests mirror :file:`test_marksman_installer.py`:
  - ``detect_installed`` — present / absent, with version probe
  - ``_install_command`` — Darwin / Linux / Windows (NotImplementedError)
  - ``install`` / ``update`` — safety gate (dry-run vs. allow_install=True)
  - ``latest_available`` — GitHub API success / offline / parse error
  - class attributes
"""

from __future__ import annotations

import json
import platform
import subprocess
import urllib.error
from typing import Any
from unittest.mock import MagicMock

import pytest

from serena.installer.smt2_installer import (
    _DEFAULT_INSTALL_DIR,
    _GITHUB_API_LATEST,
    _PINNED_VERSION,
    Smt2Installer,
    _platform_asset_name,
)


# -----------------------------------------------------------------------------
# detect_installed
# -----------------------------------------------------------------------------


def test_detect_installed_returns_absent_when_binary_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``shutil.which`` returns None, status.present must be False."""
    import serena.installer.smt2_installer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    status = Smt2Installer().detect_installed()
    assert status.present is False
    assert status.path is None
    assert status.version is None


def test_detect_installed_finds_dolmenls_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When dolmenls is on PATH and ``--version`` succeeds, status reflects it."""
    import serena.installer.smt2_installer as mod

    monkeypatch.setattr(
        mod.shutil, "which", lambda name: "/opt/local/bin/dolmenls" if name == "dolmenls" else None
    )

    def _fake_run(argv: list[str] | tuple[str, ...], **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = "dolmenls v0.10\n"
        completed.stderr = ""
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    status = Smt2Installer().detect_installed()
    assert status.present is True
    assert status.path == "/opt/local/bin/dolmenls"
    # Version probe captured the upstream version line.
    assert status.version is not None
    assert "0.10" in status.version


def test_detect_installed_handles_missing_version_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dolmenls v0.10 may not implement ``--version``; surface present=True
    with the pinned version as a fallback rather than crashing."""
    import serena.installer.smt2_installer as mod

    monkeypatch.setattr(
        mod.shutil, "which", lambda name: "/x/dolmenls" if name == "dolmenls" else None
    )

    def _fake_run(*_a: object, **_kw: Any) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 1  # non-zero — flag unsupported
        completed.stdout = ""
        completed.stderr = "unknown option --version\n"
        return completed

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    status = Smt2Installer().detect_installed()
    assert status.present is True
    assert status.path == "/x/dolmenls"
    # Falls back to pinned version since the binary exists but didn't report.
    assert status.version is None or status.version == _PINNED_VERSION


# -----------------------------------------------------------------------------
# _platform_asset_name
# -----------------------------------------------------------------------------


def test_platform_asset_name_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    assert _platform_asset_name() == "dolmenls-macos-amd64"


def test_platform_asset_name_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    assert _platform_asset_name() == "dolmenls-linux-amd64"


def test_platform_asset_name_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    assert _platform_asset_name() == "dolmenls-windows-amd64.exe"


def test_platform_asset_name_unknown_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Plan9")
    with pytest.raises(NotImplementedError):
        _platform_asset_name()


# -----------------------------------------------------------------------------
# _install_command — per-platform branching
# -----------------------------------------------------------------------------


def test_install_command_on_darwin_emits_sh_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """macOS: single ``sh -c`` chain that mkdirs + curls + chmods."""
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    cmd = Smt2Installer()._install_command()  # pyright: ignore[reportPrivateUsage]
    assert cmd[0] == "sh"
    assert cmd[1] == "-c"
    chain = cmd[2]
    assert "mkdir -p" in chain
    assert "curl" in chain
    assert "chmod +x" in chain
    # URL must point at the pinned release with the macOS asset.
    assert _PINNED_VERSION in chain
    assert "dolmenls-macos-amd64" in chain
    # No shell injection: target path is fixed to ~/.local/bin/dolmenls.
    assert str(_DEFAULT_INSTALL_DIR / "dolmenls") in chain


def test_install_command_on_linux_emits_sh_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    cmd = Smt2Installer()._install_command()  # pyright: ignore[reportPrivateUsage]
    assert cmd[0] == "sh"
    assert "dolmenls-linux-amd64" in cmd[2]


def test_install_command_on_windows_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows lacks POSIX sh + curl out of the box; surface a clear error."""
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    with pytest.raises(NotImplementedError) as exc_info:
        Smt2Installer()._install_command()  # pyright: ignore[reportPrivateUsage]
    msg = str(exc_info.value)
    assert "Windows" in msg or "windows" in msg


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
    result = Smt2Installer().install(allow_install=False)
    assert result.dry_run is True
    assert result.success is False
    assert result.command_run[0] == "sh"
    assert result.return_code is None


def test_install_with_allow_install_true_invokes_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With explicit consent the install command is actually run."""
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    import serena.installer.installer as installer_mod

    monkeypatch.setattr(
        installer_mod.shutil, "which",
        lambda name: f"/bin/{name}" if name == "sh" else None,
    )

    captured: dict[str, Any] = {}

    def _fake_run(argv: list[str] | tuple[str, ...], **kwargs: Any) -> MagicMock:
        captured["argv"] = tuple(argv)
        captured["kwargs"] = kwargs
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 0
        completed.stdout = "downloaded dolmenls\n"
        completed.stderr = ""
        return completed

    monkeypatch.setattr(installer_mod.subprocess, "run", _fake_run)
    result = Smt2Installer().install(allow_install=True)
    assert result.dry_run is False
    assert result.success is True
    assert result.return_code == 0
    assert captured["argv"][0] == "/bin/sh"
    assert captured["argv"][1] == "-c"
    # The chained sh-script is preserved verbatim.
    assert "curl" in captured["argv"][2]
    assert captured["kwargs"]["check"] is False


def test_update_with_allow_update_true_invokes_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """update() re-runs _install_command; safety gate identical to install()."""
    monkeypatch.setattr(platform, "system", lambda: "Linux")
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
    result = Smt2Installer().update(allow_update=True)
    assert result.dry_run is False
    assert result.success is True
    assert "dolmenls-linux-amd64" in captured["argv"][2]


# -----------------------------------------------------------------------------
# latest_available — GitHub API
# -----------------------------------------------------------------------------


def test_latest_available_parses_github_api_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: GitHub API returns a tagged release; we surface the tag."""
    import serena.installer.smt2_installer as mod

    payload = json.dumps({"tag_name": "v0.11", "name": "dolmen 0.11"}).encode("utf-8")

    class _FakeResponse:
        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *_a: object) -> None:
            return None

        def read(self) -> bytes:
            return payload

    def _fake_urlopen(req: object, timeout: float = 0.0) -> _FakeResponse:  # noqa: ARG001
        return _FakeResponse()

    monkeypatch.setattr(mod.urllib.request, "urlopen", _fake_urlopen)
    assert Smt2Installer().latest_available() == "v0.11"


def test_latest_available_returns_none_on_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offline / DNS / 5xx: must NOT raise; return None."""
    import serena.installer.smt2_installer as mod

    def _raise(*_a: object, **_kw: object) -> None:
        raise urllib.error.URLError("DNS failure")

    monkeypatch.setattr(mod.urllib.request, "urlopen", _raise)
    assert Smt2Installer().latest_available() is None


def test_latest_available_returns_none_on_malformed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Garbage JSON / missing tag_name field: tolerate; return None."""
    import serena.installer.smt2_installer as mod

    class _FakeResponse:
        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *_a: object) -> None:
            return None

        def read(self) -> bytes:
            return b"{not valid json"

    def _fake_urlopen(req: object, timeout: float = 0.0) -> _FakeResponse:  # noqa: ARG001
        return _FakeResponse()

    monkeypatch.setattr(mod.urllib.request, "urlopen", _fake_urlopen)
    assert Smt2Installer().latest_available() is None


def test_latest_available_uses_pinned_api_endpoint() -> None:
    """The endpoint must point at Gbury/dolmen, not a typo / wrong repo."""
    assert _GITHUB_API_LATEST == "https://api.github.com/repos/Gbury/dolmen/releases/latest"


# -----------------------------------------------------------------------------
# Class attributes
# -----------------------------------------------------------------------------


def test_class_attributes_match_spec() -> None:
    assert Smt2Installer.language == "smt2"
    assert Smt2Installer.binary_name == "dolmenls"


def test_pinned_version_is_v0_10() -> None:
    """Pin documented in the v1.4.1 plan (architectural decision §install channel)."""
    assert _PINNED_VERSION == "v0.10"
