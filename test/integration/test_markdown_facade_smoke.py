"""v1.1.1 Leaf 02 — markdown facade smoke test.

One end-to-end test that boots a real marksman against a tmp_path
workspace and exercises ``rename_heading`` through the
``ScalpelRuntime`` -> ``coordinator_for_facade`` -> marksman path.
Skips cleanly when ``marksman`` is not on PATH (production wiring
expects Leaf 03's installer to provision it; the test suite stays
hermetic on hosts without the binary).

This test proves end-to-end that:

  - ``_SPAWN_DISPATCH_TABLE["markdown"]`` resolves to
    ``MarksmanLanguageServer``;
  - ``MarkdownStrategy`` builds the single-server dict;
  - the rename request reaches marksman and returns a
    WorkspaceEdit that the facade applies to disk.

The other three facades (split / extract / organize) operate on
file content directly — their unit tests in
``test_facade_markdown.py`` already exercise the full apply path
without needing an LSP boot.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from serena.tools.scalpel_facades import RenameHeadingTool
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def _reset_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Reset the singleton runtime + redirect cache to tmp_path so the
    on-disk checkpoint store doesn't pollute the developer cache."""
    monkeypatch.setenv("O2_SCALPEL_CACHE", str(tmp_path / "cache"))
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def _require_marksman() -> None:
    if shutil.which("marksman") is None:
        pytest.skip("marksman binary not on PATH; smoke requires it")


def test_rename_heading_smoke_against_real_marksman(tmp_path: Path) -> None:
    """Boot real marksman and rename an H1 via the facade."""
    _require_marksman()

    src = tmp_path / "guide.md"
    src.write_text(
        "# Old Heading\n"
        "\n"
        "Body paragraph mentioning [[Old Heading]].\n",
        encoding="utf-8",
    )

    agent = MagicMock(name="SerenaAgent")
    agent.get_project_root.return_value = str(tmp_path)
    tool = RenameHeadingTool(agent=agent)
    object.__setattr__(tool, "get_project_root", lambda: str(tmp_path))

    payload = json.loads(
        tool.apply(
            file="guide.md",
            heading="Old Heading",
            new_name="New Heading",
            allow_out_of_workspace=True,
        ),
    )
    assert payload["applied"] is True, (
        f"rename should apply; got payload {payload!r}"
    )
    rewritten = src.read_text(encoding="utf-8")
    assert "# New Heading" in rewritten
    # marksman propagates the rename through the wiki-link. The link
    # target is slug-normalised (e.g. "new-heading"), so we assert the
    # slug appears and the old slug does not.
    assert "[[new-heading]]" in rewritten or "[[New Heading]]" in rewritten
    assert "[[Old Heading]]" not in rewritten
    assert "[[old-heading]]" not in rewritten
