"""v1.1.1 Leaf 02 — markdown facade Tool tests.

Four facades, one apply path each:

  - ``rename_heading`` — rename a heading and propagate to all
    wiki-links via marksman's ``textDocument/rename``. Uses the
    coordinator merge_rename path stubbed via the
    ``MultiServerCoordinator.merge_rename`` mock.

  - ``split_doc`` — split-by-headings; pure file mutation,
    delegates to ``markdown_doc_ops.split_doc_along_headings``.

  - ``extract_section`` — pull one section out into a new file,
    delegating to ``markdown_doc_ops.extract_section``.

  - ``organize_links`` — sort + dedup the file's links,
    delegating to ``markdown_doc_ops.organize_markdown_links``.

The latter three operate purely on the filesystem (no LSP boot
needed); ``rename_heading`` patches ``coordinator_for_facade``
so the test never touches a real marksman.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import TypeVar
from unittest.mock import AsyncMock, MagicMock

import pytest

from serena.tools import scalpel_facades as facades_mod
from serena.tools.scalpel_facades import (
    ExtractSectionTool,
    OrganizeLinksTool,
    RenameHeadingTool,
    SplitDocTool,
)
from serena.tools.scalpel_runtime import ScalpelRuntime
from serena.tools.tools_base import Tool
from serena.util.inspection import iter_subclasses


@pytest.fixture(autouse=True)
def _reset_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    monkeypatch.setenv("O2_SCALPEL_CACHE", str(tmp_path / "cache"))
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


_T = TypeVar("_T", bound=Tool)


def _build_tool(cls: type[_T], tmp_path: Path) -> _T:
    """Construct a facade Tool with a stub agent + project_root override."""
    agent = MagicMock(name="SerenaAgent")
    agent.get_project_root.return_value = str(tmp_path)
    tool = cls(agent=agent)
    object.__setattr__(tool, "get_project_root", lambda: str(tmp_path))
    return tool


# ---------------------------------------------------------------------------
# split_doc
# ---------------------------------------------------------------------------


def test_split_doc_creates_subdocs_and_replaces_source(tmp_path: Path) -> None:
    src = tmp_path / "guide.md"
    src.write_text(
        "# Intro\n"
        "\n"
        "Hello.\n"
        "\n"
        "# Setup\n"
        "\n"
        "Install.\n",
        encoding="utf-8",
    )
    tool = _build_tool(SplitDocTool, tmp_path)
    payload = json.loads(tool.apply(file="guide.md", allow_out_of_workspace=True))
    assert payload["applied"] is True

    intro = tmp_path / "intro.md"
    setup = tmp_path / "setup.md"
    assert intro.exists()
    assert setup.exists()
    # Back-link is the first line of each sub-doc.
    assert intro.read_text(encoding="utf-8").startswith("[Back to guide.md](guide.md)")
    # Source is rewritten as TOC.
    rewritten = src.read_text(encoding="utf-8")
    assert "[Intro](intro.md)" in rewritten
    assert "[Setup](setup.md)" in rewritten


def test_split_doc_no_headings_returns_no_op(tmp_path: Path) -> None:
    src = tmp_path / "plain.md"
    src.write_text("Just prose.\n", encoding="utf-8")
    tool = _build_tool(SplitDocTool, tmp_path)
    payload = json.loads(tool.apply(file="plain.md", allow_out_of_workspace=True))
    assert payload["applied"] is False
    assert payload["no_op"] is True
    # File must be untouched.
    assert src.read_text(encoding="utf-8") == "Just prose.\n"


def test_split_doc_dry_run_does_not_touch_files(tmp_path: Path) -> None:
    src = tmp_path / "guide.md"
    original = "# Intro\n\nHello.\n"
    src.write_text(original, encoding="utf-8")
    tool = _build_tool(SplitDocTool, tmp_path)
    payload = json.loads(
        tool.apply(file="guide.md", dry_run=True, allow_out_of_workspace=True),
    )
    assert payload["applied"] is False
    assert payload["no_op"] is False
    # No sub-doc should appear; source unchanged.
    assert not (tmp_path / "intro.md").exists()
    assert src.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# extract_section
# ---------------------------------------------------------------------------


def test_extract_section_creates_target_and_links_source(tmp_path: Path) -> None:
    src = tmp_path / "guide.md"
    src.write_text(
        "# Intro\n"
        "\n"
        "Hello.\n"
        "\n"
        "# Setup\n"
        "\n"
        "Install steps.\n",
        encoding="utf-8",
    )
    tool = _build_tool(ExtractSectionTool, tmp_path)
    payload = json.loads(
        tool.apply(
            file="guide.md", heading="Setup", allow_out_of_workspace=True,
        ),
    )
    assert payload["applied"] is True

    setup = tmp_path / "setup.md"
    assert setup.exists()
    assert "Install steps." in setup.read_text(encoding="utf-8")

    rewritten = src.read_text(encoding="utf-8")
    assert "[Setup](setup.md)" in rewritten
    assert "Install steps." not in rewritten


def test_extract_section_unknown_heading_returns_failure(tmp_path: Path) -> None:
    src = tmp_path / "guide.md"
    src.write_text("# Intro\n\nHello.\n", encoding="utf-8")
    tool = _build_tool(ExtractSectionTool, tmp_path)
    payload = json.loads(
        tool.apply(
            file="guide.md", heading="Missing", allow_out_of_workspace=True,
        ),
    )
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


def test_extract_section_dry_run_does_not_touch_files(tmp_path: Path) -> None:
    src = tmp_path / "guide.md"
    original = "# Setup\n\nInstall steps.\n"
    src.write_text(original, encoding="utf-8")
    tool = _build_tool(ExtractSectionTool, tmp_path)
    payload = json.loads(
        tool.apply(
            file="guide.md", heading="Setup",
            dry_run=True, allow_out_of_workspace=True,
        ),
    )
    assert payload["applied"] is False
    assert not (tmp_path / "setup.md").exists()
    assert src.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# organize_links
# ---------------------------------------------------------------------------


def test_organize_links_sorts_wiki_first_then_markdown(tmp_path: Path) -> None:
    src = tmp_path / "page.md"
    src.write_text(
        "[Zeta](https://z.example)\n"
        "[Alpha](https://a.example)\n"
        "[[wiki-bbb]]\n"
        "[[wiki-aaa]]\n",
        encoding="utf-8",
    )
    tool = _build_tool(OrganizeLinksTool, tmp_path)
    payload = json.loads(
        tool.apply(file="page.md", allow_out_of_workspace=True),
    )
    assert payload["applied"] is True

    rewritten = src.read_text(encoding="utf-8")
    wiki_aaa_pos = rewritten.index("[[wiki-aaa]]")
    wiki_bbb_pos = rewritten.index("[[wiki-bbb]]")
    alpha_pos = rewritten.index("[Alpha]")
    zeta_pos = rewritten.index("[Zeta]")
    assert wiki_aaa_pos < wiki_bbb_pos < alpha_pos < zeta_pos


def test_organize_links_no_links_returns_no_op(tmp_path: Path) -> None:
    src = tmp_path / "page.md"
    original = "# Just prose.\n\nNo links here.\n"
    src.write_text(original, encoding="utf-8")
    tool = _build_tool(OrganizeLinksTool, tmp_path)
    payload = json.loads(
        tool.apply(file="page.md", allow_out_of_workspace=True),
    )
    assert payload["applied"] is False
    assert payload["no_op"] is True
    assert src.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# rename_heading
# ---------------------------------------------------------------------------


def _patch_marksman_rename(
    monkeypatch: pytest.MonkeyPatch,
    workspace_edit: dict | None,
    find_position: dict | None = None,
) -> MagicMock:
    """Stub coordinator_for_facade so the rename path doesn't boot marksman.

    Returns the coordinator mock so callers can assert on the merge_rename
    arguments. ``find_position`` defaults to ``{"line": 0, "character": 2}``
    so the rename heading text is identifiable.
    """
    coord = MagicMock(name="MultiServerCoordinator")
    coord.find_symbol_position = AsyncMock(
        return_value=find_position or {"line": 0, "character": 2},
    )
    coord.merge_rename = AsyncMock(return_value=(workspace_edit, []))
    monkeypatch.setattr(
        facades_mod, "coordinator_for_facade",
        lambda *, language, project_root: coord,
    )
    return coord


def test_rename_heading_applies_marksman_workspace_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    src = tmp_path / "guide.md"
    src.write_text("# Old Heading\n\nBody.\n", encoding="utf-8")
    target_uri = src.as_uri()
    workspace_edit = {
        "changes": {
            target_uri: [
                {
                    "range": {
                        "start": {"line": 0, "character": 2},
                        "end": {"line": 0, "character": 13},
                    },
                    "newText": "New Heading",
                },
            ],
        },
    }
    coord = _patch_marksman_rename(monkeypatch, workspace_edit)
    tool = _build_tool(RenameHeadingTool, tmp_path)
    payload = json.loads(
        tool.apply(
            file="guide.md", heading="Old Heading",
            new_name="New Heading", allow_out_of_workspace=True,
        ),
    )
    assert payload["applied"] is True
    assert payload["lsp_ops"][0]["server"] == "marksman"
    rewritten = src.read_text(encoding="utf-8")
    assert "# New Heading" in rewritten
    # The facade resolves heading text -> position locally (no LSP roundtrip
    # — see _find_heading_position) then dispatches the rename via
    # marksman's textDocument/rename through merge_rename.
    coord.merge_rename.assert_awaited_once()


def test_rename_heading_marksman_returns_none_surfaces_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    src = tmp_path / "guide.md"
    src.write_text("# Old Heading\n", encoding="utf-8")
    _patch_marksman_rename(monkeypatch, workspace_edit=None)
    tool = _build_tool(RenameHeadingTool, tmp_path)
    payload = json.loads(
        tool.apply(
            file="guide.md", heading="Old Heading",
            new_name="New Heading", allow_out_of_workspace=True,
        ),
    )
    assert payload["applied"] is False
    assert payload["failure"]["code"] in {"SYMBOL_NOT_FOUND", "INTERNAL_ERROR"}


def test_rename_heading_dry_run_does_not_touch_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    src = tmp_path / "guide.md"
    original = "# Old Heading\n\nBody.\n"
    src.write_text(original, encoding="utf-8")
    workspace_edit = {
        "changes": {
            src.as_uri(): [
                {
                    "range": {
                        "start": {"line": 0, "character": 2},
                        "end": {"line": 0, "character": 13},
                    },
                    "newText": "New Heading",
                },
            ],
        },
    }
    _patch_marksman_rename(monkeypatch, workspace_edit)
    tool = _build_tool(RenameHeadingTool, tmp_path)
    payload = json.loads(
        tool.apply(
            file="guide.md", heading="Old Heading",
            new_name="New Heading", dry_run=True, allow_out_of_workspace=True,
        ),
    )
    assert payload["applied"] is False
    assert payload["no_op"] is False
    assert src.read_text(encoding="utf-8") == original


def test_rename_heading_unknown_heading_surfaces_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    src = tmp_path / "guide.md"
    src.write_text("# Different Heading\n", encoding="utf-8")
    tool = _build_tool(RenameHeadingTool, tmp_path)
    payload = json.loads(
        tool.apply(
            file="guide.md", heading="Missing", new_name="X",
            allow_out_of_workspace=True,
        ),
    )
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


# ---------------------------------------------------------------------------
# Auto-registration / naming
# ---------------------------------------------------------------------------


def test_facades_appear_in_iter_subclasses() -> None:
    discovered = {cls.get_name_from_cls() for cls in iter_subclasses(Tool)}
    for expected in (
        "rename_heading",
        "split_doc",
        "extract_section",
        "organize_links",
    ):
        assert expected in discovered, (
            f"{expected} not found in iter_subclasses(Tool)"
        )


def test_facade_class_names_snake_case() -> None:
    assert (
        RenameHeadingTool.get_name_from_cls() == "rename_heading"
    )
    assert SplitDocTool.get_name_from_cls() == "split_doc"
    assert (
        ExtractSectionTool.get_name_from_cls() == "extract_section"
    )
    assert (
        OrganizeLinksTool.get_name_from_cls() == "organize_links"
    )
