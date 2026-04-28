"""v1.1.1 Leaf 02 — markdown WorkspaceEdit helpers.

Pure-Python helpers consumed by the four markdown facades:

  - :func:`slugify_heading` — kebab-case filenames from heading text.
  - :func:`split_doc_along_headings` — slice a doc into per-heading
    sibling files; the source becomes a TOC of links.
  - :func:`extract_section` — pull one section out into a new file,
    leaving the source with a markdown link in its place.
  - :func:`organize_markdown_links` — sort + dedup wiki-links and
    markdown links per file (wiki-links first, then markdown, both
    alphabetised).

All helpers operate on file text directly and return LSP-shaped
``WorkspaceEdit`` dicts (``documentChanges`` form). They do NOT call
the LSP — marksman is engaged by the facade ``apply`` paths only when
the operation actually needs symbol-aware queries (rename heading uses
``textDocument/rename``; the others rely on a small inline parser
because heading semantics are stable + cheap to recompute).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Regex sources of truth (single-place per CLAUDE.md)
# ---------------------------------------------------------------------------


# ATX-style heading: leading ``#``…``######`` + space + body. We do not try to
# parse setext headings (``===``/``---``) — Leaf 02 facades target the common
# ATX case and leave setext for a follow-up.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$", re.MULTILINE)

# Wiki-link form: ``[[target]]`` or ``[[target|label]]`` — common in
# Obsidian / VitePress vaults. We capture the whole token including brackets
# so emit-order can preserve the original literal.
_WIKI_LINK_RE = re.compile(r"\[\[[^\[\]]+?\]\]")

# Inline markdown link: ``[label](url)``. We deliberately reject reference-
# style links + images (``![…]``) — those are handled separately in v1.2 if
# the need surfaces. The non-greedy class avoids running through the next
# closing bracket on a line that happens to carry two links.
_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\[\]]+?\]\([^()\s]+?\)")

# Slug normalisation: anything that's NOT a letter, digit, hyphen, or
# underscore becomes a separator candidate. We keep Unicode letters
# (``\w`` would lowercase them anyway).
_SLUG_SEPARATOR_RE = re.compile(r"[^\w]+", re.UNICODE)
_SLUG_COLLAPSE_RE = re.compile(r"[-_]+")


# ---------------------------------------------------------------------------
# slugify_heading
# ---------------------------------------------------------------------------


def slugify_heading(heading: str) -> str:
    """Render ``heading`` as a kebab-case filename slug.

    Lower-cases the text, replaces non-word characters with ``-``, then
    collapses runs of ``-``/``_`` so the result has no separator runs.
    Returns ``"section"`` when the input slugs to the empty string —
    callers can rely on a non-empty return.
    """
    lowered = heading.strip().lower()
    if not lowered:
        return "section"
    replaced = _SLUG_SEPARATOR_RE.sub("-", lowered)
    collapsed = _SLUG_COLLAPSE_RE.sub("-", replaced).strip("-")
    return collapsed or "section"


# ---------------------------------------------------------------------------
# Internal heading parser
# ---------------------------------------------------------------------------


def _parse_headings(source: str, max_depth: int) -> list[dict[str, Any]]:
    """Return one record per heading at depth ``<= max_depth``.

    Each record carries::

        {
            "level": int,         # 1 for H1, 2 for H2, …
            "text": str,          # stripped heading text
            "start_offset": int,  # offset of the leading ``#``
            "body_end_offset": int,  # exclusive end of the section's body
        }

    ``body_end_offset`` runs to the start of the next heading at depth
    ``<= max_depth`` (or to ``len(source)`` for the trailing section).
    """
    raw_matches = list(_HEADING_RE.finditer(source))
    matches = [m for m in raw_matches if len(m.group(1)) <= max_depth]
    out: list[dict[str, Any]] = []
    for idx, match in enumerate(matches):
        next_start = (
            matches[idx + 1].start() if idx + 1 < len(matches) else len(source)
        )
        out.append(
            {
                "level": len(match.group(1)),
                "text": match.group(2).strip(),
                "start_offset": match.start(),
                "body_end_offset": next_start,
            },
        )
    return out


def _full_range_of(source: str) -> dict[str, dict[str, int]]:
    """LSP ``Range`` covering ``source`` start-to-end (line/character form)."""
    if not source:
        return {
            "start": {"line": 0, "character": 0},
            "end": {"line": 0, "character": 0},
        }
    lines = source.splitlines()
    last_line = max(0, len(lines) - 1)
    last_col = len(lines[-1]) if lines else 0
    return {
        "start": {"line": 0, "character": 0},
        "end": {"line": last_line, "character": last_col},
    }


# ---------------------------------------------------------------------------
# split_doc_along_headings
# ---------------------------------------------------------------------------


def split_doc_along_headings(
    file_path: Path,
    depth: int = 1,
) -> dict[str, Any]:
    """Slice ``file_path`` along headings of depth ``<= depth``.

    Each section becomes ``<slug>.md`` next to the source. The new file's
    first line is a back-link to the parent (``[Back to <name>](<name>.md)``)
    so navigation is bidirectional. The source itself is rewritten as a
    TOC of links (one ``[Heading](slug.md)`` line per section).

    Returns an LSP-shaped ``WorkspaceEdit`` (``documentChanges`` form)
    that the facade applies via ``_apply_workspace_edit_to_disk``. The
    edit carries:

      - one ``CreateFile`` per new sibling;
      - one ``TextDocumentEdit`` per new sibling whose ``edits[0]``
        writes the section body (heading + body + back-link);
      - one ``TextDocumentEdit`` whose ``edits[0]`` rewrites the
        source's whole body as the TOC.

    Returns ``{"documentChanges": []}`` when the document carries no
    headings at the requested depth — caller can treat that as a no-op.
    """
    source = file_path.read_text(encoding="utf-8")
    headings = _parse_headings(source, max_depth=depth)
    if not headings:
        return {"documentChanges": []}

    parent_name = file_path.name
    parent_dir = file_path.parent
    document_changes: list[dict[str, Any]] = []

    toc_lines: list[str] = []
    for h in headings:
        slug = slugify_heading(h["text"])
        target = parent_dir / f"{slug}.md"
        target_uri = target.as_uri()
        section_body = source[h["start_offset"]:h["body_end_offset"]].rstrip("\n")
        new_body = (
            f"[Back to {parent_name}]({parent_name})\n"
            f"\n"
            f"{section_body}\n"
        )
        document_changes.append({"kind": "create", "uri": target_uri})
        document_changes.append(
            {
                "textDocument": {"uri": target_uri, "version": None},
                "edits": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 0},
                        },
                        "newText": new_body,
                    },
                ],
            },
        )
        toc_lines.append(f"- [{h['text']}]({slug}.md)")

    toc_body = "\n".join(toc_lines) + "\n"
    document_changes.append(
        {
            "textDocument": {"uri": file_path.as_uri(), "version": None},
            "edits": [
                {
                    "range": _full_range_of(source),
                    "newText": toc_body,
                },
            ],
        },
    )
    return {"documentChanges": document_changes}


# ---------------------------------------------------------------------------
# extract_section
# ---------------------------------------------------------------------------


def extract_section(
    file_path: Path,
    heading_text: str,
    target_path: Path | None = None,
) -> dict[str, Any]:
    """Pull the section under ``heading_text`` into a new file.

    The section runs from the matched heading line through the line
    before the next heading (any depth). Source is rewritten with the
    same prefix + ``[heading_text](<slug>.md)`` placeholder + same
    suffix (so unrelated content is preserved). The new file gets the
    full section text (heading included).

    ``target_path`` defaults to ``<source-dir>/<slug>.md``. Pass an
    explicit path to land the extract elsewhere.

    Raises :class:`KeyError` when ``heading_text`` does not match any
    heading in the source — facade callers translate this into a
    ``SYMBOL_NOT_FOUND`` failure.
    """
    source = file_path.read_text(encoding="utf-8")
    # We extract regardless of depth — caller picked the heading text.
    headings = _parse_headings(source, max_depth=6)
    match = next((h for h in headings if h["text"] == heading_text), None)
    if match is None:
        raise KeyError(heading_text)

    slug = slugify_heading(heading_text)
    if target_path is None:
        target_path = file_path.parent / f"{slug}.md"

    section_text = source[match["start_offset"]:match["body_end_offset"]].rstrip("\n") + "\n"
    target_uri = target_path.as_uri()
    rel_target = target_path.name if target_path.parent == file_path.parent else str(target_path)

    prefix = source[:match["start_offset"]]
    suffix = source[match["body_end_offset"]:]
    placeholder = f"[{heading_text}]({rel_target})\n"
    if suffix and not suffix.startswith("\n"):
        placeholder += "\n"
    rewritten_source = f"{prefix}{placeholder}{suffix}"

    document_changes: list[dict[str, Any]] = [
        {"kind": "create", "uri": target_uri},
        {
            "textDocument": {"uri": target_uri, "version": None},
            "edits": [
                {
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 0},
                    },
                    "newText": section_text,
                },
            ],
        },
        {
            "textDocument": {"uri": file_path.as_uri(), "version": None},
            "edits": [
                {
                    "range": _full_range_of(source),
                    "newText": rewritten_source,
                },
            ],
        },
    ]
    return {"documentChanges": document_changes}


# ---------------------------------------------------------------------------
# organize_markdown_links
# ---------------------------------------------------------------------------


def _markdown_link_url(token: str) -> str:
    """Pull the URL out of an inline markdown link token."""
    open_paren = token.rfind("(")
    close_paren = token.rfind(")")
    if open_paren == -1 or close_paren == -1 or close_paren <= open_paren:
        return token
    return token[open_paren + 1:close_paren]


def organize_markdown_links(file_path: Path) -> dict[str, Any]:
    """Sort + dedup the links in ``file_path``.

    Wiki-links (``[[target]]``) come first, then inline markdown links
    (``[label](url)``). Wiki-links are sorted alphabetically by the raw
    token; markdown links are sorted alphabetically by URL. Identical
    tokens are deduplicated.

    The rewritten file body is the sorted link list — one link per
    line. Returns ``{"documentChanges": []}`` when no links surface
    (no-op signal for the facade).
    """
    source = file_path.read_text(encoding="utf-8")
    wiki_tokens = _WIKI_LINK_RE.findall(source)
    md_tokens = _MARKDOWN_LINK_RE.findall(source)
    if not wiki_tokens and not md_tokens:
        return {"documentChanges": []}

    wiki_sorted = sorted(set(wiki_tokens))
    md_sorted = sorted(set(md_tokens), key=_markdown_link_url)
    body_lines = list(wiki_sorted) + list(md_sorted)
    new_text = "\n".join(body_lines) + "\n"

    return {
        "documentChanges": [
            {
                "textDocument": {"uri": file_path.as_uri(), "version": None},
                "edits": [
                    {
                        "range": _full_range_of(source),
                        "newText": new_text,
                    },
                ],
            },
        ],
    }


__all__ = [
    "extract_section",
    "organize_markdown_links",
    "slugify_heading",
    "split_doc_along_headings",
]
