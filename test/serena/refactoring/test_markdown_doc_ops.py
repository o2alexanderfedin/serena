"""v1.1.1 Leaf 02 — markdown_doc_ops helper unit tests.

Pure-Python helpers for the four markdown facades:
  - ``slugify_heading`` — kebab-case filenames from heading text;
  - ``split_doc_along_headings`` — slice a doc into per-heading siblings;
  - ``extract_section`` — pull one section into a new file with a link
    placeholder in the source;
  - ``organize_markdown_links`` — sort + dedup wiki-links and markdown
    links.

No LSP boot required — every helper operates on file text directly so
the unit suite stays hermetic. The Leaf 02 facades are the consumers
that thread these helpers through ``MarksmanLanguageServer``.
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# slugify_heading
# ---------------------------------------------------------------------------


def test_slugify_heading_basic() -> None:
    from serena.refactoring.markdown_doc_ops import slugify_heading

    assert slugify_heading("My Section") == "my-section"


def test_slugify_heading_strips_punctuation() -> None:
    from serena.refactoring.markdown_doc_ops import slugify_heading

    assert slugify_heading("My Section!") == "my-section"
    assert slugify_heading("Hello, World?") == "hello-world"


def test_slugify_heading_collapses_multiple_separators() -> None:
    from serena.refactoring.markdown_doc_ops import slugify_heading

    assert slugify_heading("A   B   C") == "a-b-c"
    assert slugify_heading("a__b--c") == "a-b-c"


def test_slugify_heading_empty_falls_back_to_section() -> None:
    from serena.refactoring.markdown_doc_ops import slugify_heading

    assert slugify_heading("") == "section"
    assert slugify_heading("!!!") == "section"


def test_slugify_heading_unicode_passthrough_lowered() -> None:
    from serena.refactoring.markdown_doc_ops import slugify_heading

    # Non-ASCII letters are kept lowercased (kebab-case stays sensible).
    assert slugify_heading("Café Menu") == "café-menu"


# ---------------------------------------------------------------------------
# split_doc_along_headings
# ---------------------------------------------------------------------------


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_split_doc_emits_one_subdoc_per_h1(tmp_path: Path) -> None:
    from serena.refactoring.markdown_doc_ops import split_doc_along_headings

    src = tmp_path / "guide.md"
    src.write_text(
        "# Intro\n"
        "\n"
        "Welcome to the guide.\n"
        "\n"
        "# Setup\n"
        "\n"
        "Install the binary.\n"
        "\n"
        "# Usage\n"
        "\n"
        "Run the binary.\n",
        encoding="utf-8",
    )

    edit = split_doc_along_headings(src, depth=1)

    # CreateFile + TextDocumentEdit per section, plus the source rewrite.
    document_changes = edit["documentChanges"]
    creates = [c for c in document_changes if c.get("kind") == "create"]
    assert len(creates) == 3
    created_uris = {c["uri"] for c in creates}
    assert any(u.endswith("/intro.md") for u in created_uris)
    assert any(u.endswith("/setup.md") for u in created_uris)
    assert any(u.endswith("/usage.md") for u in created_uris)


def test_split_doc_subdocs_carry_back_link(tmp_path: Path) -> None:
    from serena.refactoring.markdown_doc_ops import split_doc_along_headings

    src = tmp_path / "guide.md"
    src.write_text(
        "# Intro\n"
        "\n"
        "Body of intro.\n",
        encoding="utf-8",
    )

    edit = split_doc_along_headings(src, depth=1)
    document_changes = edit["documentChanges"]
    text_doc_edits = [c for c in document_changes if "edits" in c]
    # Each created file gets a paired TextDocumentEdit whose first line is
    # a back-link to the parent document.
    intro_edit = next(
        e for e in text_doc_edits
        if e["textDocument"]["uri"].endswith("/intro.md")
    )
    new_text = intro_edit["edits"][0]["newText"]
    first_line = new_text.splitlines()[0]
    assert first_line.startswith("[")
    assert "guide.md" in first_line


def test_split_doc_replaces_source_sections_with_links(tmp_path: Path) -> None:
    from serena.refactoring.markdown_doc_ops import split_doc_along_headings

    src = tmp_path / "guide.md"
    src.write_text(
        "# Intro\n"
        "\n"
        "Body of intro.\n"
        "\n"
        "# Setup\n"
        "\n"
        "Body of setup.\n",
        encoding="utf-8",
    )

    edit = split_doc_along_headings(src, depth=1)
    document_changes = edit["documentChanges"]
    src_uri = src.as_uri()
    src_edit = next(
        e for e in document_changes
        if "edits" in e and e["textDocument"]["uri"] == src_uri
    )
    rewritten = src_edit["edits"][0]["newText"]
    # The source becomes a link list pointing at the new sub-docs.
    assert "[Intro](intro.md)" in rewritten
    assert "[Setup](setup.md)" in rewritten


def test_split_doc_no_headings_returns_empty_edit(tmp_path: Path) -> None:
    from serena.refactoring.markdown_doc_ops import split_doc_along_headings

    src = tmp_path / "plain.md"
    src.write_text("Just prose. No headings.\n", encoding="utf-8")

    edit = split_doc_along_headings(src, depth=1)
    assert edit == {"documentChanges": []}


def test_split_doc_depth_two_includes_h2(tmp_path: Path) -> None:
    from serena.refactoring.markdown_doc_ops import split_doc_along_headings

    src = tmp_path / "guide.md"
    src.write_text(
        "# Intro\n"
        "\n"
        "## Sub one\n"
        "\n"
        "Sub body.\n",
        encoding="utf-8",
    )

    edit = split_doc_along_headings(src, depth=2)
    creates = [c for c in edit["documentChanges"] if c.get("kind") == "create"]
    created_uris = {c["uri"] for c in creates}
    assert any(u.endswith("/intro.md") for u in created_uris)
    assert any(u.endswith("/sub-one.md") for u in created_uris)


# ---------------------------------------------------------------------------
# extract_section
# ---------------------------------------------------------------------------


def test_extract_section_creates_target_with_section_body(tmp_path: Path) -> None:
    from serena.refactoring.markdown_doc_ops import extract_section

    src = tmp_path / "guide.md"
    src.write_text(
        "# Intro\n"
        "\n"
        "Hello.\n"
        "\n"
        "# Setup\n"
        "\n"
        "Install steps.\n"
        "\n"
        "# Usage\n"
        "\n"
        "Use it.\n",
        encoding="utf-8",
    )

    edit = extract_section(src, heading_text="Setup")

    document_changes = edit["documentChanges"]
    creates = [c for c in document_changes if c.get("kind") == "create"]
    assert len(creates) == 1
    target_uri = creates[0]["uri"]
    assert target_uri.endswith("/setup.md")

    target_edit = next(
        c for c in document_changes
        if "edits" in c and c["textDocument"]["uri"] == target_uri
    )
    new_text = target_edit["edits"][0]["newText"]
    assert "# Setup" in new_text
    assert "Install steps." in new_text


def test_extract_section_replaces_source_with_link(tmp_path: Path) -> None:
    from serena.refactoring.markdown_doc_ops import extract_section

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

    edit = extract_section(src, heading_text="Setup")
    document_changes = edit["documentChanges"]
    src_uri = src.as_uri()
    src_edit = next(
        e for e in document_changes
        if "edits" in e and e["textDocument"]["uri"] == src_uri
    )
    rewritten = src_edit["edits"][0]["newText"]
    assert "[Setup](setup.md)" in rewritten
    # The original heading body must be gone from the source.
    assert "Install steps." not in rewritten


def test_extract_section_unknown_heading_raises(tmp_path: Path) -> None:
    from serena.refactoring.markdown_doc_ops import extract_section

    src = tmp_path / "guide.md"
    src.write_text("# Intro\n\nHello.\n", encoding="utf-8")

    with pytest.raises(KeyError):
        extract_section(src, heading_text="Missing")


def test_extract_section_explicit_target_path(tmp_path: Path) -> None:
    from serena.refactoring.markdown_doc_ops import extract_section

    src = tmp_path / "guide.md"
    src.write_text(
        "# Setup\n"
        "\n"
        "Install steps.\n",
        encoding="utf-8",
    )
    target = tmp_path / "install.md"

    edit = extract_section(src, heading_text="Setup", target_path=target)
    creates = [c for c in edit["documentChanges"] if c.get("kind") == "create"]
    assert creates[0]["uri"] == target.as_uri()


# ---------------------------------------------------------------------------
# organize_markdown_links
# ---------------------------------------------------------------------------


def test_organize_links_sorts_wiki_first_then_markdown(tmp_path: Path) -> None:
    from serena.refactoring.markdown_doc_ops import organize_markdown_links

    src = tmp_path / "page.md"
    src.write_text(
        "# Links\n"
        "\n"
        "[Zeta](https://z.example)\n"
        "[Alpha](https://a.example)\n"
        "[[wiki-bbb]]\n"
        "[[wiki-aaa]]\n",
        encoding="utf-8",
    )

    edit = organize_markdown_links(src)
    src_uri = src.as_uri()
    text_edit = edit["documentChanges"][0]["edits"][0]
    new_text = text_edit["newText"]
    assert edit["documentChanges"][0]["textDocument"]["uri"] == src_uri

    # Wiki links appear before markdown links; both alphabetised.
    wiki_aaa_pos = new_text.index("[[wiki-aaa]]")
    wiki_bbb_pos = new_text.index("[[wiki-bbb]]")
    alpha_pos = new_text.index("[Alpha]")
    zeta_pos = new_text.index("[Zeta]")
    assert wiki_aaa_pos < wiki_bbb_pos < alpha_pos < zeta_pos


def test_organize_links_dedupes_identical_links(tmp_path: Path) -> None:
    from serena.refactoring.markdown_doc_ops import organize_markdown_links

    src = tmp_path / "page.md"
    src.write_text(
        "[Alpha](https://a.example)\n"
        "[Alpha](https://a.example)\n"
        "[[same-wiki]]\n"
        "[[same-wiki]]\n",
        encoding="utf-8",
    )

    edit = organize_markdown_links(src)
    new_text = edit["documentChanges"][0]["edits"][0]["newText"]
    assert new_text.count("[Alpha](https://a.example)") == 1
    assert new_text.count("[[same-wiki]]") == 1


def test_organize_links_no_links_returns_empty_edit(tmp_path: Path) -> None:
    from serena.refactoring.markdown_doc_ops import organize_markdown_links

    src = tmp_path / "page.md"
    src.write_text("# Just prose.\n\nNo links here.\n", encoding="utf-8")

    edit = organize_markdown_links(src)
    assert edit == {"documentChanges": []}
