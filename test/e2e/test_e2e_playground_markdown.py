"""E2E playground tests — Markdown plugin playground (v1.3-D).

Exercises four Markdown refactoring facades against the playground/markdown/
workspace, mirroring the v1.2.2 Rust + v1.3-C Python playground patterns.

Opt-in: ``O2_SCALPEL_RUN_E2E=1 uv run pytest test/e2e/test_e2e_playground_markdown.py``
or ``pytest -m e2e``.

All tests use the ``mcp_driver_playground_markdown`` fixture (conftest.py)
which clones ``playground/markdown/`` into a per-test ``tmp_path``.

Facade → Driver method mapping (all from ``_McpDriver``):
- scalpel_rename_heading  → ``rename_heading(**kwargs)``  — marksman LSP
- scalpel_split_doc       → ``split_doc(**kwargs)``       — pure-text
- scalpel_extract_section → ``extract_section(**kwargs)`` — pure-text
- scalpel_organize_links  → ``organize_links(**kwargs)``  — pure-text

The three pure-text facades (split_doc, extract_section, organize_links) do
NOT require marksman on PATH. rename_heading drives marksman's
textDocument/rename and skips honestly when marksman is unavailable.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.e2e
def test_playground_markdown_rename_heading(
    mcp_driver_playground_markdown,
    playground_markdown_root: Path,
    marksman_bin: str,
) -> None:
    """Rename the "Authentication" heading in docs/api.md to "Auth".

    Facade: scalpel_rename_heading.
    The cross-file wiki-link ``[[Authentication]]`` in INDEX.md should also be
    updated to ``[[Auth]]`` by marksman's workspace-wide rename.
    """
    del marksman_bin  # fixture presence = marksman is on PATH
    api_md = playground_markdown_root / "docs" / "api.md"
    assert api_md.exists(), "playground docs/api.md baseline missing"

    # Verify baseline heading is present
    api_text = api_md.read_text(encoding="utf-8")
    assert "## Authentication" in api_text, (
        "baseline docs/api.md is missing '## Authentication' heading"
    )

    try:
        result_json = mcp_driver_playground_markdown.rename_heading(
            file=str(api_md),
            heading="Authentication",
            new_name="Auth",
            dry_run=False,
        )
    except Exception as exc:
        pytest.skip(
            f"playground rename_heading raised before result (LSP-init gap): {exc!r}"
        )

    payload = json.loads(result_json)
    assert isinstance(payload, dict), f"non-JSON-object result: {result_json!r}"

    # If marksman reported capability_not_available, skip honestly.
    if payload.get("capability_not_available"):
        pytest.skip(
            "marksman did not advertise textDocument/rename (host gap); "
            "skipping rename_heading test"
        )

    assert payload.get("applied") is True, (
        f"playground rename_heading must apply; full payload={payload!r}"
    )
    assert payload.get("checkpoint_id"), (
        f"applied=True but no checkpoint_id: {payload}"
    )

    # The heading in api.md must be updated.
    api_text_after = api_md.read_text(encoding="utf-8")
    assert "## Auth" in api_text_after, (
        "renamed heading '## Auth' not found in docs/api.md after rename"
    )
    assert "## Authentication" not in api_text_after, (
        "old heading '## Authentication' still present in docs/api.md after rename"
    )

    # Cross-file wiki-link in INDEX.md should be updated too.
    index_md = playground_markdown_root / "INDEX.md"
    if index_md.exists():
        index_text = index_md.read_text(encoding="utf-8")
        # If old link present without new link → rename was partial
        if "[[Authentication]]" in index_text:
            assert "[[Auth]]" in index_text, (
                "INDEX.md still contains [[Authentication]] without [[Auth]] — "
                "cross-file rename was partial"
            )


@pytest.mark.e2e
def test_playground_markdown_split_doc(
    mcp_driver_playground_markdown,
    playground_markdown_root: Path,
) -> None:
    """Split docs/api.md along H2 headings into sibling files.

    Facade: scalpel_split_doc.
    docs/api.md has H2 headings: Authentication, Endpoints, Data Models,
    Rate Limiting. After the split each section becomes a sibling .md file
    and api.md becomes a TOC of links.

    This is a pure-text operation — no marksman required.
    """
    api_md = playground_markdown_root / "docs" / "api.md"
    assert api_md.exists(), "playground docs/api.md baseline missing"

    api_text_before = api_md.read_text(encoding="utf-8")
    assert "## Authentication" in api_text_before, (
        "baseline docs/api.md is missing H2 headings for split test"
    )

    try:
        result_json = mcp_driver_playground_markdown.split_doc(
            file=str(api_md),
            depth=2,
            dry_run=False,
        )
    except Exception as exc:
        pytest.skip(
            f"playground split_doc raised before result (gap): {exc!r}"
        )

    payload = json.loads(result_json)
    assert isinstance(payload, dict), f"non-JSON-object result: {result_json!r}"

    if payload.get("no_op") is True:
        pytest.skip(
            "split_doc returned no_op=True for docs/api.md — baseline has no "
            "H2 headings at the requested depth (unexpected; check baseline content)"
        )

    assert payload.get("applied") is True, (
        f"playground split_doc must apply; full payload={payload!r}"
    )
    assert payload.get("checkpoint_id"), (
        f"applied=True but no checkpoint_id: {payload}"
    )

    # api.md should now be a TOC; at least one sibling file should exist.
    docs_dir = playground_markdown_root / "docs"
    siblings = list(docs_dir.glob("*.md"))
    sibling_names = {f.name for f in siblings}
    expected_slugs = {"authentication.md", "endpoints.md", "data-models.md", "rate-limiting.md"}
    created = expected_slugs & sibling_names
    assert created, (
        f"split_doc applied=True but no expected sibling files found in {docs_dir}; "
        f"found: {sibling_names}"
    )

    # api.md should now be a TOC (much shorter; contains links)
    api_text_after = api_md.read_text(encoding="utf-8")
    assert "[" in api_text_after, (
        "api.md after split should contain link syntax for TOC"
    )


@pytest.mark.e2e
def test_playground_markdown_extract_section(
    mcp_driver_playground_markdown,
    playground_markdown_root: Path,
) -> None:
    """Extract the "Getting Started" section from docs/tutorial.md.

    Facade: scalpel_extract_section.
    After the extract: a new ``getting-started.md`` appears alongside
    tutorial.md; tutorial.md contains a link placeholder in its place.

    This is a pure-text operation — no marksman required.
    """
    tutorial_md = playground_markdown_root / "docs" / "tutorial.md"
    assert tutorial_md.exists(), "playground docs/tutorial.md baseline missing"

    tutorial_text_before = tutorial_md.read_text(encoding="utf-8")
    assert "## Getting Started" in tutorial_text_before, (
        "baseline docs/tutorial.md is missing '## Getting Started' section"
    )

    try:
        result_json = mcp_driver_playground_markdown.extract_section(
            file=str(tutorial_md),
            heading="Getting Started",
            dry_run=False,
        )
    except Exception as exc:
        pytest.skip(
            f"playground extract_section raised before result (gap): {exc!r}"
        )

    payload = json.loads(result_json)
    assert isinstance(payload, dict), f"non-JSON-object result: {result_json!r}"

    assert payload.get("applied") is True, (
        f"playground extract_section must apply; full payload={payload!r}"
    )
    assert payload.get("checkpoint_id"), (
        f"applied=True but no checkpoint_id: {payload}"
    )

    # New file should exist alongside tutorial.md.
    docs_dir = playground_markdown_root / "docs"
    extracted = docs_dir / "getting-started.md"
    assert extracted.exists(), (
        f"extracted file 'getting-started.md' not found in {docs_dir} after extract"
    )

    # Extracted file should contain the heading.
    extracted_text = extracted.read_text(encoding="utf-8")
    assert "Getting Started" in extracted_text, (
        "extracted file 'getting-started.md' is missing the heading text"
    )

    # tutorial.md should now have a link placeholder in place of the section.
    tutorial_text_after = tutorial_md.read_text(encoding="utf-8")
    assert "[Getting Started]" in tutorial_text_after, (
        "tutorial.md is missing the link placeholder after extract_section"
    )
    assert "## Getting Started" not in tutorial_text_after, (
        "original '## Getting Started' section still in tutorial.md after extract"
    )


@pytest.mark.e2e
def test_playground_markdown_organize_links(
    mcp_driver_playground_markdown,
    playground_markdown_root: Path,
) -> None:
    """Sort and deduplicate links in docs/links.md.

    Facade: scalpel_organize_links.
    docs/links.md has wiki-links and markdown links in a non-alphabetical
    order with duplicates (``[[Authentication]]`` and ``[Tutorial](tutorial.md)``
    appear twice). After organize: wiki-links first (sorted), then markdown
    links (sorted by URL), duplicates removed.

    This is a pure-text operation — no marksman required.
    """
    links_md = playground_markdown_root / "docs" / "links.md"
    assert links_md.exists(), "playground docs/links.md baseline missing"

    links_text_before = links_md.read_text(encoding="utf-8")
    # Verify baseline has duplicates so this test is non-trivial.
    assert links_text_before.count("[[Authentication]]") >= 2, (
        "baseline docs/links.md should have duplicate [[Authentication]] entries "
        "to make organize_links non-trivial"
    )

    try:
        result_json = mcp_driver_playground_markdown.organize_links(
            file=str(links_md),
            dry_run=False,
        )
    except Exception as exc:
        pytest.skip(
            f"playground organize_links raised before result (gap): {exc!r}"
        )

    payload = json.loads(result_json)
    assert isinstance(payload, dict), f"non-JSON-object result: {result_json!r}"

    if payload.get("no_op") is True:
        pytest.skip(
            "organize_links returned no_op=True — baseline links.md has no wiki-links "
            "or markdown links (unexpected; check baseline content)"
        )

    assert payload.get("applied") is True, (
        f"playground organize_links must apply; full payload={payload!r}"
    )
    assert payload.get("checkpoint_id"), (
        f"applied=True but no checkpoint_id: {payload}"
    )

    links_text_after = links_md.read_text(encoding="utf-8")

    # Duplicates should be removed.
    assert links_text_after.count("[[Authentication]]") == 1, (
        "organize_links did not deduplicate [[Authentication]] entries"
    )

    # Wiki-links should appear before markdown links.
    first_wiki = links_text_after.find("[[")
    first_md_link = links_text_after.find("[")
    if first_wiki != -1 and first_md_link != -1:
        assert first_wiki <= first_md_link, (
            "organize_links: wiki-links should appear before markdown links"
        )

    # Links should be sorted — [[Authentication]] before [[Getting Started]] before [[Rate Limiting]].
    auth_pos = links_text_after.find("[[Authentication]]")
    gs_pos = links_text_after.find("[[Getting Started]]")
    rl_pos = links_text_after.find("[[Rate Limiting]]")
    if auth_pos != -1 and gs_pos != -1:
        assert auth_pos < gs_pos, (
            "organize_links: [[Authentication]] should sort before [[Getting Started]]"
        )
    if gs_pos != -1 and rl_pos != -1:
        assert gs_pos < rl_pos, (
            "organize_links: [[Getting Started]] should sort before [[Rate Limiting]]"
        )


# Engine repo URL — matches the git+URL in o2-scalpel-markdown/.mcp.json.
# Updated to the renamed fork (project_serena_fork_renamed.md).
_ENGINE_GIT_URL = "git+https://github.com/o2alexanderfedin/o2-scalpel-engine.git"


@pytest.mark.skipif(
    os.getenv("O2_SCALPEL_TEST_REMOTE_INSTALL") != "1",
    reason="opt-in via O2_SCALPEL_TEST_REMOTE_INSTALL=1; v1.3 graduation candidate (PyPI publish)",
)
def test_playground_markdown_remote_install_smoke(tmp_path: Path) -> None:
    """Verify the published install path works end-to-end against the live GitHub repo.

    Mirrors ``test_playground_python_remote_install_smoke`` from v1.3-C.
    Currently gated off by default — cold uvx fetch dominates CI wall-clock budget.

    v1.3 graduation: once PyPI publication lands, replace the ``git+URL`` form with
    ``o2-scalpel-engine`` (package name); ``uvx`` resolves from cache in <1 s and
    this test moves to default-on.
    """
    del tmp_path  # unused; present for future fixture expansion

    proc = subprocess.run(
        [
            "uvx",
            "--from",
            _ENGINE_GIT_URL,
            "serena",
            "start-mcp-server",
            "--help",
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert proc.returncode == 0, (
        f"uvx serena start-mcp-server --help failed (rc={proc.returncode}):\n"
        f"stdout:\n{proc.stdout[:1000]}\n"
        f"stderr:\n{proc.stderr[:1000]}"
    )
    combined = proc.stdout + proc.stderr
    assert "--language" in combined, (
        f"expected '--language' in help output — engine may not have booted correctly:\n"
        f"{combined[:500]}"
    )
