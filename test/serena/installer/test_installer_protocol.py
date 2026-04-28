"""v1.1.1 Leaf 03 C1 — ``LspInstaller`` ABC + ``InstalledStatus`` + ``InstallResult``.

These tests pin the schema for the two pydantic boundary models AND the
ABC contract: an installer subclass MUST declare ``language``,
``binary_name``, and implement ``detect_installed`` / ``latest_available``
/ ``_install_command`` / ``install`` / ``update``. The safety gate
(``allow_install`` / ``allow_update`` defaulting to ``False``) is
enforced by the base class — subclasses that opt to actually invoke
``subprocess.run`` get the gate for free.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from serena.installer.installer import InstalledStatus, InstallResult, LspInstaller


def test_installed_status_is_frozen_pydantic_with_expected_fields() -> None:
    status = InstalledStatus(present=True, version="1.2.3", path="/usr/local/bin/foo")
    assert status.present is True
    assert status.version == "1.2.3"
    assert status.path == "/usr/local/bin/foo"
    # frozen — assignment must raise
    with pytest.raises(ValidationError):
        status.present = False  # type: ignore[misc]


def test_installed_status_allows_optional_version_and_path_when_absent() -> None:
    status = InstalledStatus(present=False, version=None, path=None)
    assert status.present is False
    assert status.version is None
    assert status.path is None


def test_installed_status_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        InstalledStatus(
            present=True, version="1.0", path="/x", undeclared_field="bad",  # pyright: ignore[reportCallIssue]
        )


def test_install_result_is_frozen_pydantic_with_expected_fields() -> None:
    result = InstallResult(
        success=True,
        command_run=("brew", "install", "marksman"),
        stdout="==> Installing marksman\n",
        stderr="",
        return_code=0,
        dry_run=False,
    )
    assert result.success is True
    assert result.command_run == ("brew", "install", "marksman")
    assert result.stdout.startswith("==>")
    assert result.return_code == 0
    assert result.dry_run is False
    with pytest.raises(ValidationError):
        result.success = False  # type: ignore[misc]


def test_install_result_dry_run_default_is_safe() -> None:
    """A bare ``InstallResult`` with no return code must not pretend success."""
    result = InstallResult(
        success=False,
        command_run=("brew", "install", "marksman"),
        stdout="",
        stderr="",
        return_code=None,
        dry_run=True,
    )
    assert result.dry_run is True
    assert result.return_code is None
    assert result.success is False


# -----------------------------------------------------------------------------
# ABC contract
# -----------------------------------------------------------------------------


def test_lsp_installer_is_abstract_and_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        LspInstaller()  # type: ignore[abstract]  # pyright: ignore[reportAbstractUsage]


def test_subclass_missing_required_methods_cannot_instantiate() -> None:
    class _Incomplete(LspInstaller):  # pyright: ignore[reportImplicitAbstractClass]
        language = "x"
        binary_name = "x"

    with pytest.raises(TypeError):
        _Incomplete()  # type: ignore[abstract]  # pyright: ignore[reportAbstractUsage]


def test_concrete_subclass_can_instantiate_and_exposes_class_attributes() -> None:
    class _Stub(LspInstaller):
        language = "stub"
        binary_name = "stub-lsp"

        def detect_installed(self) -> InstalledStatus:
            return InstalledStatus(present=False, version=None, path=None)

        def latest_available(self) -> str | None:
            return None

        def _install_command(self) -> tuple[str, ...]:
            return ("echo", "stub")

    inst = _Stub()
    assert inst.language == "stub"
    assert inst.binary_name == "stub-lsp"
    status = inst.detect_installed()
    assert status.present is False


def test_install_default_safety_gate_returns_dry_run_without_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``install(allow_install=False)`` must NEVER touch subprocess.run."""
    import subprocess as _subprocess

    sentinel: list[str] = []

    def _explode(*_a: object, **_kw: object) -> None:
        sentinel.append("subprocess.run was invoked")
        raise AssertionError("subprocess.run was invoked under allow_install=False")

    monkeypatch.setattr(_subprocess, "run", _explode)

    class _Stub(LspInstaller):
        language = "stub"
        binary_name = "stub-lsp"

        def detect_installed(self) -> InstalledStatus:
            return InstalledStatus(present=False, version=None, path=None)

        def latest_available(self) -> str | None:
            return None

        def _install_command(self) -> tuple[str, ...]:
            return ("brew", "install", "stub-lsp")

    result = _Stub().install(allow_install=False)
    assert result.dry_run is True
    assert result.success is False
    assert result.command_run == ("brew", "install", "stub-lsp")
    assert sentinel == []


def test_update_default_safety_gate_returns_dry_run_without_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess as _subprocess

    def _explode(*_a: object, **_kw: object) -> None:
        raise AssertionError("subprocess.run was invoked under allow_update=False")

    monkeypatch.setattr(_subprocess, "run", _explode)

    class _Stub(LspInstaller):
        language = "stub"
        binary_name = "stub-lsp"

        def detect_installed(self) -> InstalledStatus:
            return InstalledStatus(present=True, version="1.0", path="/x/stub-lsp")

        def latest_available(self) -> str | None:
            return "2.0"

        def _install_command(self) -> tuple[str, ...]:
            return ("brew", "upgrade", "stub-lsp")

    result = _Stub().update(allow_update=False)
    assert result.dry_run is True
    assert result.success is False
    assert result.command_run == ("brew", "upgrade", "stub-lsp")
