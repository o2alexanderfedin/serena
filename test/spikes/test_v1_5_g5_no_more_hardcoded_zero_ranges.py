"""v1.5 G5 — regression guard against hardcoded (0,0) range literals.

After Wave 2 (G3a, G4-7/8/9, G6 ME-6) closed every spec-cited site
(HI-13), the only `{"line": 0, "character": 0}` literals that may
survive in ``scalpel_facades.py`` production code paths are explicitly
annotated degenerate fallbacks (e.g. ``compute_file_range`` failed
because the file does not exist on disk). Each such site MUST carry a
``# G5-VERIFIED`` comment within 3 lines of the literal so future
code-review catches new unreviewed sites.

This test enforces both halves of the contract:

1. **Annotated allow-list** — each surviving literal is gated by the
   ``# G5-VERIFIED:`` marker. Reviewers can audit the markers.
2. **Adjacent-pair regression** — no NEW ``start = (0,0), end = (0,0)``
   adjacency may be introduced (the HI-13 anti-pattern proper).

These are catch-net tests; if Wave 2 fix leaves regress, this test
fires loudly with the offending line number and source excerpt.
"""

from __future__ import annotations

import re
from pathlib import Path

FACADE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "serena"
    / "tools"
    / "scalpel_facades.py"
)

# Match the canonical zero-position literal — both ``"line": 0, "character": 0``
# orderings are tolerated. Whitespace permissive.
_ZERO_POS = re.compile(
    r"\{\s*\"line\"\s*:\s*0\s*,\s*\"character\"\s*:\s*0\s*\}",
    re.MULTILINE | re.DOTALL,
)

# Adjacent ``start = (0,0), end = (0,0)`` — the HI-13 anti-pattern proper.
_ZERO_PAIR = re.compile(
    r"start\s*=\s*\{\s*\"line\"\s*:\s*0\s*,\s*\"character\"\s*:\s*0\s*\}"
    r"\s*,\s*"
    r"end\s*=\s*\{\s*\"line\"\s*:\s*0\s*,\s*\"character\"\s*:\s*0\s*\}",
    re.MULTILINE | re.DOTALL,
)

_VERIFIED_MARKER = re.compile(r"#\s*G5-VERIFIED\b")


def _strip_docstrings_and_comments(text: str) -> str:
    """Remove triple-quoted strings only — keep inline comments so the
    G5-VERIFIED markers remain visible to the marker-adjacency check."""
    return re.sub(r'"""[\s\S]*?"""', "", text)


def test_no_unreviewed_zero_position_literals_in_facades() -> None:
    """Every surviving ``{"line": 0, "character": 0}`` literal in
    production code paths must carry a ``# G5-VERIFIED:`` marker
    within 3 lines (above or below). Unannotated literals fail loud."""
    raw = FACADE.read_text(encoding="utf-8")
    body = _strip_docstrings_and_comments(raw)
    lines = body.splitlines()

    offenders: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        if not _ZERO_POS.search(line):
            continue
        # Look 3 lines above + below for the marker.
        window_start = max(0, idx - 3)
        window_end = min(len(lines), idx + 4)
        window = "\n".join(lines[window_start:window_end])
        if not _VERIFIED_MARKER.search(window):
            offenders.append((idx + 1, line.strip()))

    assert offenders == [], (
        "Found unannotated `{\"line\": 0, \"character\": 0}` literal(s) in "
        "scalpel_facades.py production code. Either route through "
        "compute_file_range / find_symbol_range, or add a "
        "`# G5-VERIFIED` comment within 3 lines justifying the "
        f"degenerate range. Offenders (line, content):\n{offenders!r}"
    )


def test_no_adjacent_zero_pair_in_facades() -> None:
    """The HI-13 anti-pattern ``start=(0,0), end=(0,0)`` must not appear
    as an adjacency in production code paths. compute_file_range or a
    real symbol range is required."""
    raw = FACADE.read_text(encoding="utf-8")
    body = _strip_docstrings_and_comments(raw)
    matches = _ZERO_PAIR.findall(body)
    assert matches == [], (
        f"Found {len(matches)} HI-13 (0,0)→(0,0) adjacency pair(s); "
        f"replace with compute_file_range or a real symbol range:\n{matches}"
    )
