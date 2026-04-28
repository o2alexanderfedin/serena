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
