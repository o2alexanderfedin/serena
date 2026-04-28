"""v1.1.1 Leaf 03 C3 — ``ScalpelInstallLspServersTool`` tests.

The tool is the LLM-facing surface for the installer infrastructure.
Default: ``dry_run=True`` + ``allow_install=False`` — surfaces what
WOULD run, never invokes. Explicit ``dry_run=False`` + ``allow_install=True``
unlocks actual install.

Auto-registration is asserted last (``iter_subclasses(Tool)`` mirrors
the v1.1.1 _V11_1_NAMES expectation in test_stage_1g_t9_tool_discovery).
"""

from __future__ import annotations

import json
import platform
import re
from typing import Any
from unittest.mock import MagicMock

import pytest

from serena.tools.scalpel_primitives import ScalpelInstallLspServersTool


def _make_tool() -> ScalpelInstallLspServersTool:
    return ScalpelInstallLspServersTool(agent=MagicMock(name="SerenaAgent"))


def test_default_apply_returns_dry_run_for_all_known_languages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No args → dry-run for every registered installer (currently: marksman)."""
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    payload = json.loads(_make_tool().apply())
    assert isinstance(payload, dict)
    assert "markdown" in payload
    md = payload["markdown"]
    assert md["action"] in {"install", "update", "noop"}
    # The exact action depends on whether marksman is installed on this host;
    # what matters is that ``command`` is the planned argv and dry_run==True.
    assert md["command"] == ["brew", "install", "marksman"]
    assert md["dry_run"] is True


def test_apply_with_explicit_languages_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    payload = json.loads(_make_tool().apply(languages=["markdown"]))
    assert set(payload.keys()) == {"markdown"}
    assert payload["markdown"]["dry_run"] is True
    assert payload["markdown"]["command"] == ["brew", "install", "marksman"]


def test_apply_unknown_language_reports_skipped() -> None:
    payload = json.loads(_make_tool().apply(languages=["cobol"]))
    assert "cobol" in payload
    assert payload["cobol"]["action"] == "skipped"
    assert "no installer registered" in payload["cobol"]["reason"].lower()


def test_apply_allow_install_without_dry_run_false_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Safety: allow_install=True is meaningless without explicit dry_run=False.

    The default ``dry_run=True`` overrides ``allow_install=True``: the
    install command (``brew install marksman``) MUST NOT be invoked.
    detect_installed legitimately calls ``marksman --version`` to probe
    the version, so we discriminate on the argv (``install`` vs
    ``--version``) rather than blanket-erroring on every subprocess call.
    """
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    import serena.installer.installer as installer_mod

    install_calls: list[tuple[str, ...]] = []

    def _track(argv: list[str] | tuple[str, ...], **_kw: Any) -> MagicMock:
        argv_t = tuple(argv)
        if "install" in argv_t and any("brew" in a or "snap" in a for a in argv_t):
            install_calls.append(argv_t)
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "2026-02-08\n" if "--version" in argv_t else "[]"
        completed.stderr = ""
        return completed

    monkeypatch.setattr(installer_mod.subprocess, "run", _track)
    payload = json.loads(
        _make_tool().apply(languages=["markdown"], allow_install=True),
    )
    md = payload["markdown"]
    # Default dry_run=True overrides allow_install=True.
    assert md["dry_run"] is True
    assert md["command"] == ["brew", "install", "marksman"]
    # The install argv was NEVER invoked.
    assert install_calls == []


def test_apply_with_allow_install_true_invokes_installer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dry_run=False + allow_install=True actually runs the install command."""
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    import serena.installer.installer as installer_mod

    # Force "absent" by patching shutil.which globally — both detect_installed
    # (resolves the LSP binary) and the install path (resolves brew) share the
    # same shutil module reference. Returning None for marksman + a stable
    # path for brew lets us pin the captured argv.
    def _which(name: str) -> str | None:
        if name == "marksman":
            return None
        return f"/usr/local/bin/{name}"

    monkeypatch.setattr(installer_mod.shutil, "which", _which)

    captured: dict[str, Any] = {}

    def _fake_run(argv: list[str] | tuple[str, ...], **_kw: Any) -> MagicMock:
        captured["argv"] = tuple(argv)
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "==> Installing marksman\n"
        completed.stderr = ""
        return completed

    monkeypatch.setattr(installer_mod.subprocess, "run", _fake_run)
    # marksman_mod.subprocess and installer_mod.subprocess reference the
    # same module object — patching one patches both. Belt-and-braces:
    # explicitly override marksman_mod's subprocess.run too in case the
    # module reference ever forks.
    import serena.installer.marksman_installer as marksman_mod

    monkeypatch.setattr(marksman_mod.subprocess, "run", _fake_run)

    payload = json.loads(_make_tool().apply(
        languages=["markdown"],
        dry_run=False,
        allow_install=True,
    ))
    md = payload["markdown"]
    assert md["dry_run"] is False
    assert md["action"] == "install"
    assert md["success"] is True
    # subprocess.run actually fired with the planned brew argv.
    assert captured["argv"][1:] == ("install", "marksman")


def test_apply_with_dry_run_false_but_allow_install_false_does_not_invoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even with dry_run=False, install only runs if allow_install=True."""
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    import subprocess

    monkeypatch.setattr(
        subprocess, "run",
        lambda *_a, **_kw: (_ for _ in ()).throw(
            AssertionError("subprocess.run invoked without allow_install=True"),
        ),
    )
    import serena.installer.marksman_installer as marksman_mod

    monkeypatch.setattr(marksman_mod.shutil, "which", lambda _name: None)
    payload = json.loads(_make_tool().apply(
        languages=["markdown"],
        dry_run=False,
        allow_install=False,
    ))
    md = payload["markdown"]
    # Action is still "install" (binary is absent) but no subprocess invocation.
    assert md["dry_run"] is True
    assert md["action"] == "install"


def test_apply_when_already_installed_reports_noop_or_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When detect_installed.present=True and latest matches, action=noop."""
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    import serena.installer.marksman_installer as marksman_mod

    monkeypatch.setattr(
        marksman_mod.shutil, "which",
        lambda name: "/opt/homebrew/bin/marksman" if name == "marksman" else None,
    )

    def _fake_marksman_run(argv: list[str] | tuple[str, ...], **_kw: Any) -> MagicMock:
        completed = MagicMock()
        completed.returncode = 0
        # detect_installed asks `marksman --version`; latest_available skipped
        # because brew is missing on PATH.
        if "--version" in argv:
            completed.stdout = "2026-02-08\n"
            completed.stderr = ""
        else:
            completed.stdout = "[]"
            completed.stderr = ""
        return completed

    monkeypatch.setattr(marksman_mod.subprocess, "run", _fake_marksman_run)
    payload = json.loads(_make_tool().apply(languages=["markdown"]))
    md = payload["markdown"]
    # Without a known latest, action falls through to ``noop`` (already installed).
    assert md["detected"]["present"] is True
    assert md["action"] in {"noop", "update"}


# -----------------------------------------------------------------------------
# Auto-registration / MCP wiring
# -----------------------------------------------------------------------------


def test_tool_auto_registered_via_iter_subclasses() -> None:
    """The new tool surfaces in iter_subclasses(Tool) with the expected name."""
    from serena.tools.tools_base import Tool
    from serena.util.inspection import iter_subclasses

    discovered = {cls.get_name_from_cls() for cls in iter_subclasses(Tool)}
    assert "scalpel_install_lsp_servers" in discovered


def test_tool_class_name_matches_snake_cased_form() -> None:
    assert (
        ScalpelInstallLspServersTool.get_name_from_cls()
        == "scalpel_install_lsp_servers"
    )


def test_tool_apply_docstring_under_thirty_words() -> None:
    """§5.4 router-signage rule shared by every Stage 1G primitive."""
    doc = ScalpelInstallLspServersTool.apply.__doc__ or ""
    head = doc.split(":param", 1)[0].split(":return", 1)[0]
    word_count = len(re.findall(r"\b\w+\b", head))
    assert word_count <= 30, (
        f"ScalpelInstallLspServersTool.apply docstring head exceeds 30 words "
        f"({word_count}): {head!r}"
    )


def test_tool_class_docstring_present() -> None:
    assert ScalpelInstallLspServersTool.__doc__
    assert ScalpelInstallLspServersTool.__doc__.strip()


def test_tool_exported_from_tools_package() -> None:
    """``from serena.tools import ScalpelInstallLspServersTool`` works."""
    from serena import tools as tools_pkg

    assert hasattr(tools_pkg, "ScalpelInstallLspServersTool")
    assert tools_pkg.ScalpelInstallLspServersTool is ScalpelInstallLspServersTool


def test_make_mcp_tool_succeeds() -> None:
    """SerenaMCPFactory accepts the new tool over the JSON-RPC boundary."""
    from serena.mcp import SerenaMCPFactory

    agent = MagicMock(name="SerenaAgent")
    agent.get_context.return_value = MagicMock(tool_description_overrides={})
    tool = ScalpelInstallLspServersTool(agent=agent)
    mcp_tool = SerenaMCPFactory.make_mcp_tool(tool, openai_tool_compatible=False)
    assert mcp_tool.name == "scalpel_install_lsp_servers"
    assert mcp_tool.description


# -----------------------------------------------------------------------------
# v1.2 Leaf A — registry covers all 6 LSP servers (markdown + 5 back-ports)
# -----------------------------------------------------------------------------


def _patched_run(argv: list[str] | tuple[str, ...], **_kw: Any) -> MagicMock:
    """Default fake subprocess.run for registry-wide dry-run sweeps.

    Returns success for any --version probe (so detect_installed sees a
    version string when a binary is mocked-present) and an empty pipx
    list payload otherwise so latest_available falls through to None.
    """
    completed = MagicMock()
    completed.returncode = 0
    argv_t = tuple(argv)
    if "--version" in argv_t:
        completed.stdout = "stub-version\n"
    elif "list" in argv_t and "--json" in argv_t:
        completed.stdout = json.dumps({"venvs": {}})
    else:
        completed.stdout = ""
    completed.stderr = ""
    return completed


def test_apply_default_languages_covers_all_six_installers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v1.2 registry surfaces markdown + 5 back-port slots — six entries total."""
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    # Patch every installer's subprocess.run so the sweep stays in dry-run land.
    import serena.installer.basedpyright_installer as bpr_mod
    import serena.installer.clippy_installer as clp_mod
    import serena.installer.installer as installer_mod
    import serena.installer.marksman_installer as mks_mod
    import serena.installer.pylsp_installer as pylsp_mod
    import serena.installer.ruff_installer as ruff_mod
    import serena.installer.rust_analyzer_installer as ra_mod

    for mod in (installer_mod, mks_mod, ra_mod, pylsp_mod, bpr_mod, ruff_mod, clp_mod):
        monkeypatch.setattr(mod.subprocess, "run", _patched_run)

    payload = json.loads(_make_tool().apply())
    expected_keys = {
        "markdown",
        "rust",
        "python",
        "python-basedpyright",
        "python-ruff",
        "rust-clippy",
    }
    assert set(payload.keys()) == expected_keys
    for lang in expected_keys:
        entry = payload[lang]
        # Every entry has a planned argv tuple and is in safe dry-run mode.
        assert entry["dry_run"] is True
        assert isinstance(entry["command"], list)
        assert entry["command"]  # non-empty
        assert entry["action"] in {"install", "update", "noop"}


def test_apply_filter_to_rust_only_returns_rust_analyzer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``languages=['rust']`` filters down to RustAnalyzerInstaller alone."""
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    import serena.installer.installer as installer_mod
    import serena.installer.rust_analyzer_installer as ra_mod

    monkeypatch.setattr(installer_mod.subprocess, "run", _patched_run)
    monkeypatch.setattr(ra_mod.subprocess, "run", _patched_run)
    payload = json.loads(_make_tool().apply(languages=["rust"]))
    assert set(payload.keys()) == {"rust"}
    assert payload["rust"]["command"] == [
        "rustup", "component", "add", "rust-analyzer",
    ]
    assert payload["rust"]["dry_run"] is True


def test_apply_filter_to_python_basedpyright_returns_basedpyright(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``python-basedpyright`` slot resolves to BasedpyrightInstaller (secondary Python LSP)."""
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    import serena.installer.basedpyright_installer as bpr_mod
    import serena.installer.installer as installer_mod

    monkeypatch.setattr(installer_mod.subprocess, "run", _patched_run)
    monkeypatch.setattr(bpr_mod.subprocess, "run", _patched_run)
    payload = json.loads(_make_tool().apply(languages=["python-basedpyright"]))
    assert set(payload.keys()) == {"python-basedpyright"}
    assert payload["python-basedpyright"]["command"] == [
        "pipx", "install", "basedpyright",
    ]


def test_apply_filter_to_python_ruff_returns_ruff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    import serena.installer.installer as installer_mod
    import serena.installer.ruff_installer as ruff_mod

    monkeypatch.setattr(installer_mod.subprocess, "run", _patched_run)
    monkeypatch.setattr(ruff_mod.subprocess, "run", _patched_run)
    payload = json.loads(_make_tool().apply(languages=["python-ruff"]))
    assert payload["python-ruff"]["command"] == ["pipx", "install", "ruff"]


def test_apply_filter_to_python_returns_pylsp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The primary ``python`` slot resolves to PylspInstaller, not basedpyright/ruff."""
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    import serena.installer.installer as installer_mod
    import serena.installer.pylsp_installer as pylsp_mod

    monkeypatch.setattr(installer_mod.subprocess, "run", _patched_run)
    monkeypatch.setattr(pylsp_mod.subprocess, "run", _patched_run)
    payload = json.loads(_make_tool().apply(languages=["python"]))
    assert payload["python"]["command"] == ["pipx", "install", "python-lsp-server"]


def test_apply_filter_to_rust_clippy_returns_clippy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    import serena.installer.clippy_installer as clp_mod
    import serena.installer.installer as installer_mod

    monkeypatch.setattr(installer_mod.subprocess, "run", _patched_run)
    monkeypatch.setattr(clp_mod.subprocess, "run", _patched_run)
    payload = json.loads(_make_tool().apply(languages=["rust-clippy"]))
    assert payload["rust-clippy"]["command"] == [
        "rustup", "component", "add", "clippy",
    ]


def test_installer_registry_has_six_entries() -> None:
    """Direct check on the registry helper — v1.2 ships exactly 6 installer slots."""
    from serena.tools.scalpel_primitives import _installer_registry

    registry = _installer_registry()
    assert set(registry.keys()) == {
        "markdown",
        "rust",
        "python",
        "python-basedpyright",
        "python-ruff",
        "rust-clippy",
    }
    # Each value is a concrete LspInstaller subclass.
    from serena.installer.installer import LspInstaller

    for cls in registry.values():
        assert issubclass(cls, LspInstaller)
        # Class can be instantiated (concrete, not abstract).
        cls()
