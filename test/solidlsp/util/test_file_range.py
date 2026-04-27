"""Unit tests for ``solidlsp.util.file_range.compute_file_range``.

Stage v0.2.0 follow-up #02 (Leaf 02): the helper centralises the LSP
end-of-file coordinate math currently duplicated across the 16 deferred
Rust integration tests, and provides the preflight position oracle the
``RustAnalyzer`` adapter uses to reject out-of-range positions before
the LSP round-trip.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from solidlsp.util.file_range import compute_file_range


def test_empty_file_returns_zero_zero(tmp_path: Path) -> None:
    """Empty files have a zero-length whole-file range at (0, 0)."""
    p = tmp_path / "empty.rs"
    p.write_text("", encoding="utf-8")
    start, end = compute_file_range(p)
    assert start == {"line": 0, "character": 0}
    assert end == {"line": 0, "character": 0}


def test_single_line_no_trailing_newline(tmp_path: Path) -> None:
    """Single-line files end at (0, len(line))."""
    p = tmp_path / "one.rs"
    p.write_text("fn main() {}", encoding="utf-8")
    start, end = compute_file_range(p)
    assert start == {"line": 0, "character": 0}
    assert end == {"line": 0, "character": 12}


def test_multiline_with_trailing_newline(tmp_path: Path) -> None:
    """A trailing LF moves the EOF position onto a fresh line at column 0."""
    p = tmp_path / "two.rs"
    p.write_text("fn a() {}\nfn b() {}\n", encoding="utf-8")
    start, end = compute_file_range(p)
    assert start == {"line": 0, "character": 0}
    assert end == {"line": 2, "character": 0}


def test_multiline_no_trailing_newline(tmp_path: Path) -> None:
    """No trailing LF: EOF is on the last content line at (n-1, len(last))."""
    p = tmp_path / "three.rs"
    p.write_text("fn a() {}\nfn b() {}", encoding="utf-8")
    start, end = compute_file_range(p)
    assert start == {"line": 0, "character": 0}
    assert end == {"line": 1, "character": 9}


def test_crlf_line_endings(tmp_path: Path) -> None:
    """CRLF counts as a single line break (LSP §3.17 PositionEncoding)."""
    p = tmp_path / "crlf.rs"
    p.write_bytes(b"a\r\nb\r\n")
    _, end = compute_file_range(p)
    assert end == {"line": 2, "character": 0}


def test_lone_cr_treated_as_line_break(tmp_path: Path) -> None:
    """Bare CR (legacy classic-Mac) also counts as one line break per LSP."""
    p = tmp_path / "cr.rs"
    p.write_bytes(b"a\rb\r")
    _, end = compute_file_range(p)
    assert end == {"line": 2, "character": 0}


def test_only_newline(tmp_path: Path) -> None:
    """A single LF produces an empty trailing line at (1, 0)."""
    p = tmp_path / "nl.rs"
    p.write_text("\n", encoding="utf-8")
    start, end = compute_file_range(p)
    assert start == {"line": 0, "character": 0}
    assert end == {"line": 1, "character": 0}


def test_missing_file_raises(tmp_path: Path) -> None:
    """A missing path must raise ``FileNotFoundError``."""
    with pytest.raises(FileNotFoundError):
        compute_file_range(tmp_path / "nope.rs")


def test_accepts_str_path(tmp_path: Path) -> None:
    """Accepts ``str`` paths as well as ``Path`` for caller convenience."""
    p = tmp_path / "str.rs"
    p.write_text("x", encoding="utf-8")
    _, end = compute_file_range(str(p))
    assert end == {"line": 0, "character": 1}
