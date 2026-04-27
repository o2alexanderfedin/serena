"""LSP-compliant whole-file range computation.

Centralises the end-of-file coordinate math previously duplicated across
the 16 deferred Rust integration tests (and the conftest
``whole_file_range`` fixture). Also acts as the preflight oracle for
position-strict servers like rust-analyzer, which reject out-of-range
positions per LSP §3.17 PositionEncoding rather than clamping.

Stage v0.2.0 follow-up #02 (Leaf 02). See
``stage-1h-results/PROGRESS.md:86`` and ``WHAT-REMAINS.md:103``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

LSPPosition = dict[str, int]
"""An LSP-style 0-indexed position: ``{"line": int, "character": int}``."""

PathLike = Union[str, Path]
"""Accepts ``str`` paths as well as ``pathlib.Path`` for caller convenience."""


def compute_file_range(path: PathLike) -> tuple[LSPPosition, LSPPosition]:
    r"""Return ``(start, end)`` LSP positions covering the entire file.

    The returned ``start`` is always ``{"line": 0, "character": 0}``.
    ``end`` points past the last character of the file:

    - empty file ........................ ``(0, 0)``
    - single line, no trailing newline .. ``(0, len(line))``
    - file ending with ``\n`` ........... ``(N, 0)`` where ``N`` is the
      number of line terminators
    - file with no trailing newline ..... ``(N-1, len(last))``

    Line-terminator handling follows LSP §3.17: each of ``\n``, ``\r``,
    and ``\r\n`` counts as exactly one line break. Encoding is the LSP
    default UTF-16; for ASCII-only fixtures (the smoke-test corpus) this
    is identical to a UTF-8 character count.

    The file is read as UTF-8. Non-UTF-8 sources (e.g., latin-1, UTF-16
    BOM-prefixed files) raise ``UnicodeDecodeError``; callers that need to
    support arbitrary encodings should detect/decode upstream and pass a
    materialised path of UTF-8 text, or catch the exception explicitly.

    :param path: file to measure. Accepts ``str`` or ``pathlib.Path``.
    :raises FileNotFoundError: if ``path`` does not exist.
    :raises UnicodeDecodeError: if ``path`` is not valid UTF-8.
    """
    text = Path(path).read_text(encoding="utf-8")
    if not text:
        return (
            {"line": 0, "character": 0},
            {"line": 0, "character": 0},
        )

    # Normalise CRLF -> LF first so a 2-byte terminator counts as one
    # line break. Then collapse lone CR (legacy classic-Mac) onto LF.
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    last_index = len(lines) - 1
    last_char = len(lines[-1])
    return (
        {"line": 0, "character": 0},
        {"line": last_index, "character": last_char},
    )
