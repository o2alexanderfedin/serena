"""Multi-LSP coordination for Python (scope-report §11).

Only Python uses multi-LSP at MVP: pylsp + basedpyright + ruff.
pylsp-mypy is DROPPED at MVP (Phase 0 P5a / SUMMARY §6) — the merger
never receives a pylsp-mypy candidate, but the ``provenance`` Literal
keeps it for v1.1 schema compatibility.

This module is the only place that knows about server identities.
Below: ``LanguageServerCodeEditor._apply_workspace_edit`` sees a single
merged ``WorkspaceEdit`` per call (with provenance annotations).
Above: facades see merged ``MergedCodeAction`` lists with
``suppressed_alternatives`` populated only when ``O2_SCALPEL_DEBUG_MERGE=1``.
"""

from __future__ import annotations

from typing import Any, Iterator, Literal, cast

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# §11.6 schemas — verbatim per scope report.
# ---------------------------------------------------------------------------

ProvenanceLiteral = Literal[
    "pylsp-rope",
    "pylsp-base",
    "basedpyright",
    "ruff",
    "pylsp-mypy",
    "rust-analyzer",
]


class SuppressedAlternative(BaseModel):
    """An alternative dropped during the §11.1 two-stage merge.

    Only attached to ``MergedCodeAction.suppressed_alternatives`` when
    ``O2_SCALPEL_DEBUG_MERGE=1``.
    """

    title: str
    provenance: str
    reason: Literal["lower_priority", "duplicate_title", "duplicate_edit"]


class MergedCodeAction(BaseModel):
    """A code action that survived the §11.1 two-stage merge.

    Carries ``provenance`` so the LLM can audit which server produced
    the winner; carries ``suppressed_alternatives`` (debug-only) so a
    diff against the unmerged set is reconstructable.
    """

    id: str
    title: str
    kind: str
    disabled_reason: str | None
    is_preferred: bool
    provenance: ProvenanceLiteral
    suppressed_alternatives: list[SuppressedAlternative] = Field(default_factory=list)


class ServerTimeoutWarning(BaseModel):
    """Single-server timeout entry, surfaced by ``broadcast()``."""

    server: str
    method: str
    timeout_ms: int
    after_ms: int


class MultiServerBroadcastResult(BaseModel):
    """Result of fanning a request to N servers in parallel.

    Internal to ``MultiServerCoordinator``; facades never see this
    shape — they see ``list[MergedCodeAction]``.
    """

    responses: dict[str, Any] = Field(default_factory=dict)
    timeouts: list[ServerTimeoutWarning] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Imports needed for runtime behaviors below.
# ---------------------------------------------------------------------------

import asyncio
import datetime
import json
import os
import time

# Methods broadcast() can dispatch. Each entry maps an LSP wire method
# name to the SolidLanguageServer facade name that implements it.
# ``textDocument/rename`` is intentionally NOT broadcast — it goes
# through ``merge_rename()`` (T8) which is single-primary per §11.3.
_BROADCAST_DISPATCH: dict[str, str] = {
    "textDocument/codeAction": "request_code_actions",
    "codeAction/resolve": "resolve_code_action",
    "workspace/executeCommand": "execute_command",
}


def _default_broadcast_timeout_ms() -> int:
    """Per-call default; ``O2_SCALPEL_BROADCAST_TIMEOUT_MS`` overrides."""
    raw = os.environ.get("O2_SCALPEL_BROADCAST_TIMEOUT_MS")
    if raw is None:
        return 2000
    try:
        v = int(raw)
        return v if v > 0 else 2000
    except ValueError:
        return 2000


# ---------------------------------------------------------------------------
# §11.1 + Phase 0 P2 — sub-kind normalization for priority-table lookup.
# ---------------------------------------------------------------------------

# Server-suffix tokens recognized by the merger. Stage 1E adapters
# may extend this set; per Phase 0 P2 only "ruff" appears in the wild
# at MVP, but defensive entries cover future expansions and the
# hierarchical-collision case noted in §11.2.
_KNOWN_SERVER_SUFFIXES: frozenset[str] = frozenset({
    "ruff",
    "pylsp-rope",
    "pylsp-base",
    "pylsp-mypy",
    "basedpyright",
    "rust-analyzer",
})

# Base families against which the §11.1 priority table is keyed.
# A hierarchical kind ``<family>.<server-suffix>`` collapses to
# ``<family>`` for priority-table lookup. Other hierarchies (e.g.
# ``refactor.extract.function``) are NOT collapsed — they're semantic
# sub-actions, not server tags.
_PRIORITY_BASE_FAMILIES: frozenset[str] = frozenset({
    "source.organizeImports",
    "source.fixAll",
    "quickfix",
    "refactor.extract",
    "refactor.inline",
    "refactor.rewrite",
    "refactor",
    "source",
})


def _normalize_kind(kind: str) -> str:
    """Collapse hierarchical server-suffix kinds onto their priority family.

    Per LSP §3.18.1, CodeActionKind values are dot-separated hierarchies
    (e.g. ``source.organizeImports.ruff``). Phase 0 P2 confirmed ruff
    publishes under such suffixes while pylsp-rope publishes the bare
    family. The §11.1 priority table is keyed by family, so the merger
    rewrites suffixed kinds before lookup.

    Rule: if ``kind`` decomposes into ``<family>.<server>`` where
    ``<family>`` is in ``_PRIORITY_BASE_FAMILIES`` and ``<server>`` is in
    ``_KNOWN_SERVER_SUFFIXES``, return ``<family>``. Otherwise return
    ``kind`` unchanged.

    Examples:
      ``source.organizeImports.ruff`` → ``source.organizeImports``
      ``source.fixAll.ruff`` → ``source.fixAll``
      ``refactor.extract.function`` → ``refactor.extract.function`` (kept)
      ``quickfix`` → ``quickfix`` (already a family)
    """
    if not kind or "." not in kind:
        return kind
    head, _, tail = kind.rpartition(".")
    if head in _PRIORITY_BASE_FAMILIES and tail in _KNOWN_SERVER_SUFFIXES:
        return head
    return kind


# ---------------------------------------------------------------------------
# §11.1 Stage-1 priority table (verbatim per scope report).
# ---------------------------------------------------------------------------
#
# Keys are ``(family, quickfix_context)`` — context is None for non-quickfix
# families. Values are server-id lists ordered highest → lowest priority.
# pylsp-mypy is INTENTIONALLY ABSENT — Phase 0 P5a / SUMMARY §6 dropped it
# from the active MVP set; merger never receives a pylsp-mypy candidate.
_PRIORITY_TABLE: dict[tuple[str, str | None], tuple[str, ...]] = {
    ("source.organizeImports", None): ("ruff", "pylsp-rope", "basedpyright"),
    ("source.fixAll", None): ("ruff",),
    ("quickfix", "auto-import"): ("basedpyright", "pylsp-rope"),
    ("quickfix", "lint-fix"): ("ruff", "pylsp-rope", "basedpyright"),
    ("quickfix", "type-error"): ("basedpyright",),  # pylsp-mypy DROPPED
    ("quickfix", "other"): ("pylsp-rope", "basedpyright", "ruff"),
    ("refactor.extract", None): ("pylsp-rope",),
    ("refactor.inline", None): ("pylsp-rope",),
    ("refactor.rewrite", None): ("pylsp-rope", "basedpyright"),
    ("refactor", None): ("pylsp-rope", "basedpyright"),
    ("source", None): ("ruff", "pylsp-rope", "basedpyright"),
}


# Diagnostic-code → quickfix-context lookup. Sourced from
# specialist-python.md §5.3; entries cover the codes Phase 0 P4
# observed plus ruff's lint codes (Fxxx, Exxx, Wxxx prefixes).
_AUTO_IMPORT_CODES: frozenset[str] = frozenset({
    "undefined-name",          # pylsp / pyflakes
    "reportUndefinedVariable",  # basedpyright
    "reportPossiblyUndefined",  # basedpyright
    "F821",                     # ruff: undefined name
})

_TYPE_ERROR_CODE_PREFIXES: tuple[str, ...] = (
    "report",  # basedpyright family: reportArgumentType, reportCallIssue, reportInvalidTypeForm, ...
)
_TYPE_ERROR_CODE_EXACT: frozenset[str] = frozenset({
    "type-error",
    "incompatible-type",
})

_LINT_FIX_CODE_PREFIXES: tuple[str, ...] = (
    "E", "W", "F", "I", "B", "C", "N", "S", "PL",  # ruff/flake8/pylint families
)


def _classify_quickfix_context(diagnostic: dict[str, Any] | None) -> str:
    """Bucket a diagnostic into a quickfix sub-context per §11.1.

    Returns one of: ``"auto-import"``, ``"lint-fix"``, ``"type-error"``,
    ``"other"``. ``"other"`` is the fallback for empty / unrecognized
    diagnostics. Used to disambiguate the three quickfix priority rows.
    """
    if not diagnostic:
        return "other"
    code = diagnostic.get("code")
    if code is None:
        return "other"
    code_str = str(code)
    if code_str in _AUTO_IMPORT_CODES:
        return "auto-import"
    if code_str in _TYPE_ERROR_CODE_EXACT:
        return "type-error"
    if any(code_str.startswith(p) for p in _TYPE_ERROR_CODE_PREFIXES):
        return "type-error"
    # Lint-fix prefix check is last — it's the loosest.
    if any(
        len(code_str) > len(p) and code_str.startswith(p) and code_str[len(p)].isdigit()
        for p in _LINT_FIX_CODE_PREFIXES
    ):
        return "lint-fix"
    return "other"


def _apply_priority(
    candidates: list[tuple[str, dict[str, Any]]],
    family: str,
    quickfix_context: str | None,
) -> list[tuple[str, dict[str, Any]]]:
    """Stage-1 of the §11.1 merge: drop lower-priority winners; preserve
    ``disabled.reason`` actions; bucket unknown servers at lowest priority.

    Inputs are pre-grouped per family by the caller (``merge_code_actions``);
    ``quickfix_context`` is non-None only for ``family == "quickfix"`` and
    is one of ``"auto-import"`` / ``"lint-fix"`` / ``"type-error"`` /
    ``"other"`` per ``_classify_quickfix_context``.

    Returns the surviving ``(server_id, action)`` tuples in priority
    order. Disabled-reason actions are appended after the winner so
    callers can surface them per §11.2 ("Server returns disabled.reason
    set → preserve in merged list; do not silently drop").
    """
    if not candidates:
        return []
    key = (family, quickfix_context)
    priority = _PRIORITY_TABLE.get(key, ())

    # Partition.
    disabled: list[tuple[str, dict[str, Any]]] = []
    active: list[tuple[str, dict[str, Any]]] = []
    for sid, action in candidates:
        if isinstance(action.get("disabled"), dict) and action["disabled"].get("reason"):
            disabled.append((sid, action))
        else:
            active.append((sid, action))

    # Pick the highest-priority active server present in the candidate set.
    winner: tuple[str, dict[str, Any]] | None = None
    for sid in priority:
        match = next(((s, a) for s, a in active if s == sid), None)
        if match is not None:
            winner = match
            break

    out: list[tuple[str, dict[str, Any]]] = []
    if winner is not None:
        out.append(winner)
    elif active:
        # Family unknown OR no priority entry matched any candidate server.
        # Per §11.2 row "kind:null/unrecognized" → bucket lowest; we still
        # surface ONE candidate so the LLM has something to act on.
        out.append(active[0])

    # Preserve disabled actions per §11.2.
    out.extend(disabled)
    return out



# ---------------------------------------------------------------------------
# §11.1 Stage-2 — dedup-by-equivalence (title equality + lazy WorkspaceEdit).
# ---------------------------------------------------------------------------

import re

_TITLE_PREFIXES_TO_STRIP: tuple[str, ...] = (
    "quick fix: ",
    "quickfix: ",
    "add: ",
    "add ",
    "fix: ",
)
_TITLE_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_title(title: str) -> str:
    """Normalize a code-action title for Stage-2 equality comparison.

    Lowercases, strips conventional leading prefixes (``"Add: "``,
    ``"Quick fix: "``, etc.), collapses internal whitespace. Per §11.1
    Stage-2 example: ``"Import 'numpy'"`` and ``"Add import: numpy"``
    both normalize to a comparable form.
    """
    s = title.strip().lower()
    # Strip prefixes repeatedly (longest-first so ``"add: "`` wins
    # over ``"add "`` when both could match).
    changed = True
    while changed:
        changed = False
        for prefix in sorted(_TITLE_PREFIXES_TO_STRIP, key=len, reverse=True):
            if s.startswith(prefix):
                s = s[len(prefix):].strip()
                changed = True
                break
    s = _TITLE_WHITESPACE_RE.sub(" ", s)
    return s


def _workspace_edit_to_canonical_set(edit: dict[str, Any]) -> frozenset[tuple[Any, ...]]:
    """Reduce a ``WorkspaceEdit`` (or legacy ``changes`` map) to a set of
    ``(uri, start_line, start_char, end_line, end_char, newText)`` tuples.

    Set-shaped so two edits whose internal list ordering differs still
    compare equal (some servers re-order, some don't). Stage-2 equality
    is set-of-edits, not list-of-edits.
    """
    out: set[tuple[Any, ...]] = set()
    if "documentChanges" in edit:
        for change in edit["documentChanges"]:
            kind = change.get("kind")
            if kind in ("create", "rename", "delete"):
                # File-level operations: keep them in the canonical form
                # so structural equality includes them.
                if kind == "create":
                    out.add(("create", change["uri"]))
                elif kind == "delete":
                    out.add(("delete", change["uri"]))
                else:  # rename
                    out.add(("rename", change["oldUri"], change["newUri"]))
                continue
            uri = change["textDocument"]["uri"]
            for te in change.get("edits", []):
                rng = te["range"]
                out.add((
                    uri,
                    rng["start"]["line"], rng["start"]["character"],
                    rng["end"]["line"], rng["end"]["character"],
                    te["newText"],
                ))
    if "changes" in edit:
        for uri, edits in edit["changes"].items():
            for te in edits:
                rng = te["range"]
                out.add((
                    uri,
                    rng["start"]["line"], rng["start"]["character"],
                    rng["end"]["line"], rng["end"]["character"],
                    te["newText"],
                ))
    return frozenset(out)


def _workspace_edits_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Set-equality on the canonical (uri, range, newText) tuples."""
    return _workspace_edit_to_canonical_set(a) == _workspace_edit_to_canonical_set(b)


def _dedup(
    candidates: list[tuple[str, dict[str, Any]]],
    priority: tuple[str, ...],
) -> list[tuple[str, dict[str, Any], list[tuple[str, dict[str, Any], str]]]]:
    """Stage-2 of the §11.1 merge: dedup by equivalence.

    For every pair of survivors, compare normalized titles first
    (cheap); if titles don't match, compare WorkspaceEdit structural
    equality lazily. If either matches, keep the higher-priority
    server's action; record the dropped one with its reason.

    Returns ``(server_id, action, dropped_alternatives)`` per surviving
    cluster. ``dropped_alternatives`` is a list of
    ``(server_id, action, reason)`` triples where ``reason`` is one of
    ``"duplicate_title"`` / ``"duplicate_edit"``. ``"lower_priority"``
    is the responsibility of ``_apply_priority`` (Stage 1), not this
    function.
    """
    if not candidates:
        return []
    if len(candidates) == 1:
        sid, action = candidates[0]
        return [(sid, action, [])]

    def _rank(server_id: str) -> int:
        try:
            return priority.index(server_id)
        except ValueError:
            return len(priority)  # unknown servers sort last

    # Sort candidates highest-priority-first so the first member of any
    # cluster is automatically the winner.
    ranked = sorted(candidates, key=lambda sa: _rank(sa[0]))

    # Cluster IDs assigned greedily.
    cluster_winner_idx_per_member: list[int] = [-1] * len(ranked)
    titles = [_normalize_title(a.get("title", "")) for _, a in ranked]
    for i in range(len(ranked)):
        if cluster_winner_idx_per_member[i] != -1:
            continue
        cluster_winner_idx_per_member[i] = i
        for j in range(i + 1, len(ranked)):
            if cluster_winner_idx_per_member[j] != -1:
                continue
            same_title = titles[i] != "" and titles[i] == titles[j]
            same_edit = False
            if not same_title:
                edit_i = ranked[i][1].get("edit")
                edit_j = ranked[j][1].get("edit")
                if isinstance(edit_i, dict) and isinstance(edit_j, dict):
                    same_edit = _workspace_edits_equal(edit_i, edit_j)
            if same_title or same_edit:
                cluster_winner_idx_per_member[j] = i

    # Build the output: one entry per winner, with dropped sibling info.
    out: list[tuple[str, dict[str, Any], list[tuple[str, dict[str, Any], str]]]] = []
    for winner_idx in range(len(ranked)):
        if cluster_winner_idx_per_member[winner_idx] != winner_idx:
            continue
        winner_sid, winner_action = ranked[winner_idx]
        dropped: list[tuple[str, dict[str, Any], str]] = []
        winner_title = titles[winner_idx]
        for other_idx in range(len(ranked)):
            if other_idx == winner_idx or cluster_winner_idx_per_member[other_idx] != winner_idx:
                continue
            other_sid, other_action = ranked[other_idx]
            other_title = titles[other_idx]
            if winner_title != "" and winner_title == other_title:
                reason = "duplicate_title"
            else:
                reason = "duplicate_edit"
            dropped.append((other_sid, other_action, reason))
        out.append((winner_sid, winner_action, dropped))
    return out


# ---------------------------------------------------------------------------
# §11.2 disagreement helpers — case 1 (overlap classification) + case 5
# (kind:null / unrecognized → quickfix.other).
# ---------------------------------------------------------------------------


def _flatten_text_edits(edit: dict[str, Any]) -> list[tuple]:
    """Flatten a WorkspaceEdit to a sortable list of (uri, sl, sc, el, ec, newText) tuples.

    File-level operations (``create`` / ``rename`` / ``delete``) are
    excluded — only TextDocumentEdit hunks are flattened, since the
    §11.2 case-1 overlap analysis is byte-range based.
    """
    out: list[tuple] = []
    for change in edit.get("documentChanges", []) or []:
        if change.get("kind") in ("create", "rename", "delete"):
            continue
        uri = change.get("textDocument", {}).get("uri", "")
        for te in change.get("edits", []) or []:
            r = te.get("range", {})
            s = r.get("start", {}); e = r.get("end", {})
            out.append((uri, s.get("line", 0), s.get("character", 0),
                        e.get("line", 0), e.get("character", 0),
                        te.get("newText", "")))
    return out


def _range_contains(outer: tuple, inner: tuple) -> bool:
    """Does ``outer`` (sl, sc, el, ec) geometrically contain ``inner``?
    Inclusive on both ends."""
    o_sl, o_sc, o_el, o_ec = outer
    i_sl, i_sc, i_el, i_ec = inner
    # inner.start >= outer.start
    if (i_sl, i_sc) < (o_sl, o_sc):
        return False
    # inner.end <= outer.end
    if (i_el, i_ec) > (o_el, o_ec):
        return False
    return True


def _classify_overlap(higher: dict[str, Any], lower: dict[str, Any]) -> str:
    """§11.2 case 1: classify the relationship between two WorkspaceEdits.

    Returns:
        "subset_lossless"  — every change in ``lower`` is also in ``higher``
                             (each lower hunk's range is geometrically
                             contained by some same-uri hunk in ``higher``)
        "subset_lossy"     — ``lower`` carries extra changes ``higher`` does not
                             (at least one lower hunk has no covering higher hunk
                             AND at least one lower hunk IS covered → partial
                             overlap with extras)
        "disjoint"         — no lower hunk is covered by any higher hunk
                             (caller should NOT call this; reach via Stage-2
                             dedup instead)
    """
    higher_tuples = _flatten_text_edits(higher)
    lower_tuples = _flatten_text_edits(lower)

    # Group higher hunks by uri for O(N) containment checks.
    higher_by_uri: dict[str, list[tuple]] = {}
    for h in higher_tuples:
        higher_by_uri.setdefault(h[0], []).append(h[1:5])  # (sl, sc, el, ec)

    covered = 0
    uncovered = 0
    for uri, l_sl, l_sc, l_el, l_ec, _ in lower_tuples:
        candidates = higher_by_uri.get(uri, [])
        inner = (l_sl, l_sc, l_el, l_ec)
        if any(_range_contains(outer, inner) for outer in candidates):
            covered += 1
        else:
            uncovered += 1

    if covered == 0:
        return "disjoint"
    if uncovered == 0:
        return "subset_lossless"
    return "subset_lossy"


_KNOWN_KIND_PREFIXES: tuple[str, ...] = (
    "source.organizeImports", "source.fixAll", "source",
    "quickfix", "refactor.extract", "refactor.inline", "refactor.rewrite", "refactor",
)


def _bucket_unknown_kind(kind: str | None) -> str:
    """§11.2 case 5: map null/unrecognized kinds to ``quickfix.other`` (lowest priority).

    A kind is "known" iff its dotted prefix matches one of the canonical
    LSP CodeActionKind buckets (LSP §3.18.1). Anything else collapses to
    the lowest-priority sentinel ``quickfix.other``.
    """
    if not kind:
        return "quickfix.other"
    for known in _KNOWN_KIND_PREFIXES:
        if kind == known or kind.startswith(known + "."):
            return kind
    return "quickfix.other"


# ---------------------------------------------------------------------------
# §11.7 invariants — apply-clean / syntactic-validity / disabled / boundary.
# ---------------------------------------------------------------------------

import ast
from pathlib import Path
from urllib.parse import unquote, urlparse


def _uri_to_path(uri: str) -> Path:
    """LSP file:// URI → local Path. Handles percent-encoding."""
    parsed = urlparse(uri)
    return Path(unquote(parsed.path))


def _iter_text_document_edits(edit: dict[str, Any]) -> list[dict[str, Any]]:
    """Yield the TextDocumentEdit entries from a WorkspaceEdit (both
    documentChanges and legacy changes-map shapes)."""
    out: list[dict[str, Any]] = []
    for change in edit.get("documentChanges", []) or []:
        if "textDocument" in change and "edits" in change:
            out.append(change)
    if "changes" in edit:
        for uri, edits in edit["changes"].items():
            out.append({
                "textDocument": {"uri": uri, "version": None},
                "edits": list(edits),
            })
    return out


def _check_apply_clean(
    edit: dict[str, Any],
    document_versions: dict[str, int],
) -> tuple[bool, str | None]:
    """Invariant 1: every TextDocumentEdit's textDocument.version must
    match the server-tracked version (or be None for version-agnostic)."""
    for tde in _iter_text_document_edits(edit):
        td = tde["textDocument"]
        uri = td["uri"]
        edit_version = td.get("version")
        if edit_version is None:
            continue
        tracked = document_versions.get(uri)
        if tracked is None:
            continue
        if tracked != edit_version:
            return False, f"STALE_VERSION: uri={uri} edit_version={edit_version} tracked={tracked}"
    return True, None


def _check_syntactic_validity(edit: dict[str, Any]) -> tuple[bool, str | None]:
    """Invariant 2: post-apply ast.parse on every .py file the edit touches.

    Apply each edit to a copy of the file in memory, then ast.parse.
    """
    for tde in _iter_text_document_edits(edit):
        uri = tde["textDocument"]["uri"]
        path = _uri_to_path(uri)
        if path.suffix != ".py":
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except OSError:
            continue  # file may not yet exist (CreateFile then edit) — skip
        sorted_edits = sorted(
            tde["edits"],
            key=lambda e: (e["range"]["start"]["line"], e["range"]["start"]["character"]),
            reverse=True,
        )
        new_src = _apply_text_edits_in_memory(src, sorted_edits)
        try:
            ast.parse(new_src)
        except SyntaxError as exc:
            return False, f"SyntaxError@{path.name}: {exc.msg} (line {exc.lineno})"
    return True, None


def _apply_text_edits_in_memory(src: str, sorted_edits: list[dict[str, Any]]) -> str:
    """Naive line-based edit application for invariant checking only.
    Edits MUST be pre-sorted descending so earlier edits don't shift
    later edits' offsets."""
    lines = src.splitlines(keepends=True)
    # Convert to a single string with character offsets for slicing.
    line_offsets = [0]
    for ln in lines:
        line_offsets.append(line_offsets[-1] + len(ln))
    text = src
    for te in sorted_edits:
        rng = te["range"]
        s_line, s_char = rng["start"]["line"], rng["start"]["character"]
        e_line, e_char = rng["end"]["line"], rng["end"]["character"]
        if s_line >= len(line_offsets):
            s_offset = len(text)
        else:
            s_offset = line_offsets[s_line] + s_char
        if e_line >= len(line_offsets):
            e_offset = len(text)
        else:
            e_offset = line_offsets[e_line] + e_char
        s_offset = min(s_offset, len(text))
        e_offset = min(e_offset, len(text))
        text = text[:s_offset] + te["newText"] + text[e_offset:]
        # Recompute line_offsets — naive but correct for invariant check.
        new_lines = text.splitlines(keepends=True)
        line_offsets = [0]
        for ln in new_lines:
            line_offsets.append(line_offsets[-1] + len(ln))
    return text


def _check_workspace_boundary(
    edit: dict[str, Any],
    workspace_folders: list[str],
    extra_paths: tuple[str, ...] = (),
) -> tuple[bool, str | None]:
    """Invariant 4 (§11.8): every documentChanges entry's path must lie
    under workspace_folders or extra_paths. Reject the WHOLE edit on
    first failure (atomic — no partial application)."""
    # Lazy import to avoid a hard solidlsp coupling in pure-unit usage.
    from solidlsp.ls import SolidLanguageServer

    rejected: list[str] = []
    for change in edit.get("documentChanges", []) or []:
        kind = change.get("kind")
        uris: list[str] = []
        if kind == "create" or kind == "delete":
            uris.append(change["uri"])
        elif kind == "rename":
            uris.append(change["oldUri"])
            uris.append(change["newUri"])
        else:
            uris.append(change["textDocument"]["uri"])
        for uri in uris:
            target = str(_uri_to_path(uri))
            if not SolidLanguageServer.is_in_workspace(
                target=target,
                roots=list(workspace_folders),
                extra_paths=extra_paths,
            ):
                rejected.append(target)
    if "changes" in edit:
        for uri in edit["changes"]:
            target = str(_uri_to_path(uri))
            if not SolidLanguageServer.is_in_workspace(
                target=target,
                roots=list(workspace_folders),
                extra_paths=extra_paths,
            ):
                rejected.append(target)
    if rejected:
        return False, f"OUT_OF_WORKSPACE_EDIT_BLOCKED: rejected_paths={rejected}"
    return True, None


# ---------------------------------------------------------------------------
# §11.3 + Phase 0 P6 — rename merger with whole-file ↔ surgical reconciliation.
# ---------------------------------------------------------------------------

import difflib

# Per-language primary server for textDocument/rename per §11.3.
_RENAME_PRIMARY_BY_LANGUAGE: dict[str, str] = {
    "python": "pylsp-rope",
    "rust": "rust-analyzer",
}


def _reconcile_rename_edits(
    edit: dict[str, Any],
    source_reader,
) -> list[tuple[str, dict[str, Any]]]:
    """Normalize a rename WorkspaceEdit to a list of surgical hunks.

    Detects the pylsp pattern (single edit per file whose range spans
    a multi-line block) and converts to per-line hunks via
    ``difflib.unified_diff``. Already-surgical edits (e.g.
    basedpyright's token-range edits) pass through unchanged.

    ``source_reader`` is called as ``source_reader(uri) -> str`` and
    returns the current file contents.

    Returns ``list[(uri, text_edit_dict)]`` flattened across files.
    """
    out: list[tuple[str, dict[str, Any]]] = []
    for change in edit.get("documentChanges", []) or []:
        if "textDocument" not in change or "edits" not in change:
            continue
        uri = change["textDocument"]["uri"]
        for te in change["edits"]:
            rng = te["range"]
            line_span = rng["end"]["line"] - rng["start"]["line"]
            if line_span <= 1:
                # Surgical: keep as-is.
                out.append((uri, te))
                continue
            # Whole-file shape: derive surgical hunks.
            try:
                src = source_reader(uri)
            except Exception:  # noqa: BLE001
                # Fall back to surfacing the whole-file edit verbatim.
                out.append((uri, te))
                continue
            old_lines = src.splitlines(keepends=True)
            new_lines = te["newText"].splitlines(keepends=True)
            for hunk in _line_hunks(old_lines, new_lines):
                out.append((uri, hunk))
    return out


def _line_hunks(old_lines: list[str], new_lines: list[str]) -> list[dict[str, Any]]:
    """Produce minimal-range TextEdits via difflib.SequenceMatcher.
    Each opcode that isn't 'equal' becomes one TextEdit covering the
    affected old-line range, with the new-line text as newText."""
    sm = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    out: list[dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        out.append({
            "range": {
                "start": {"line": i1, "character": 0},
                "end": {"line": i2, "character": 0},
            },
            "newText": "".join(new_lines[j1:j2]),
        })
    return out


def _rename_symdiff(winner: dict[str, Any], loser: dict[str, Any], source_reader) -> dict[str, int]:
    """Symmetric-difference summary of two rename WorkspaceEdits.
    Both are reconciled to surgical form first; the result counts
    the per-(uri, range, newText) tuples unique to each side."""
    w_set = {
        (uri, te["range"]["start"]["line"], te["range"]["start"]["character"],
         te["range"]["end"]["line"], te["range"]["end"]["character"], te["newText"])
        for uri, te in _reconcile_rename_edits(winner, source_reader)
    }
    l_set = {
        (uri, te["range"]["start"]["line"], te["range"]["start"]["character"],
         te["range"]["end"]["line"], te["range"]["end"]["character"], te["newText"])
        for uri, te in _reconcile_rename_edits(loser, source_reader)
    }
    return {
        "only_in_winner": len(w_set - l_set),
        "only_in_loser": len(l_set - w_set),
        "shared": len(w_set & l_set),
    }


class MultiServerCoordinator:
    """Coordinator for the §11 multi-LSP merge.

    Holds a ``dict[server_id, server]`` pool. Servers are duck-typed:
    in production they are ``SolidLanguageServer`` subclasses (Stage 1E
    adapters). In Stage 1D unit tests they are ``_FakeServer`` doubles
    from ``test/spikes/conftest.py``. Method shapes are identical.
    """

    def __init__(self, servers: dict[str, Any]) -> None:
        self._servers = dict(servers)
        self._action_edits: dict[str, dict[str, Any]] = {}

    @property
    def servers(self) -> dict[str, Any]:
        return dict(self._servers)

    async def broadcast(
        self,
        method: str,
        kwargs: dict[str, Any],
        timeout_ms: int | None = None,
    ) -> MultiServerBroadcastResult:
        """Fan ``method`` with ``kwargs`` to every server in the pool.

        Returns a ``MultiServerBroadcastResult`` collecting:
          - ``responses``: ``{server_id: response}`` for servers that
            answered within ``timeout_ms``.
          - ``timeouts``: ``ServerTimeoutWarning`` per server that
            exceeded the deadline.
          - ``errors``: ``{server_id: stringified-exception}`` per
            server that raised.

        ``timeout_ms`` defaults to ``$O2_SCALPEL_BROADCAST_TIMEOUT_MS``
        or 2000ms per §11.2 row "Server times out (>2 s for codeAction)".
        """
        facade_name = _BROADCAST_DISPATCH.get(method)
        if facade_name is None:
            raise ValueError(f"unsupported broadcast method: {method!r}")
        deadline_ms = timeout_ms if timeout_ms is not None else _default_broadcast_timeout_ms()
        timeout_s = deadline_ms / 1000.0

        async def _one(server_id: str, server: Any) -> tuple[str, Any | BaseException, float]:
            facade = getattr(server, facade_name)
            t0 = time.monotonic()
            try:
                resp = await asyncio.wait_for(facade(**kwargs), timeout=timeout_s)
                return server_id, resp, (time.monotonic() - t0) * 1000.0
            except asyncio.TimeoutError as exc:
                return server_id, exc, (time.monotonic() - t0) * 1000.0
            except BaseException as exc:  # noqa: BLE001
                return server_id, exc, (time.monotonic() - t0) * 1000.0

        gathered = await asyncio.gather(
            *[_one(sid, srv) for sid, srv in self._servers.items()],
            return_exceptions=False,
        )
        out = MultiServerBroadcastResult()
        for sid, resp_or_exc, after_ms in gathered:
            if isinstance(resp_or_exc, asyncio.TimeoutError):
                out.timeouts.append(
                    ServerTimeoutWarning(
                        server=sid,
                        method=method,
                        timeout_ms=deadline_ms,
                        after_ms=int(after_ms),
                    )
                )
            elif isinstance(resp_or_exc, BaseException):
                out.errors[sid] = f"{type(resp_or_exc).__name__}: {resp_or_exc}"
            else:
                out.responses[sid] = resp_or_exc
        return out

    async def _resolve_if_needed(self, server_id: str, action: dict[str, Any]) -> dict[str, Any]:
        """Call codeAction/resolve when the action lacks both ``edit``
        and ``command``. Per Phase 0 SUMMARY §6: rust-analyzer is
        deferred-resolution; pylsp-rope is direct command-typed."""
        has_edit = isinstance(action.get("edit"), dict) and bool(action["edit"])
        has_command = isinstance(action.get("command"), dict) and bool(action["command"])
        if has_edit or has_command:
            return action
        srv = self._servers[server_id]
        try:
            return await srv.resolve_code_action(action)
        except Exception:  # noqa: BLE001
            # Resolution failure leaves the candidate as-is; T7
            # invariants will drop it (no edit, no command, won't apply).
            return action

    async def merge_code_actions(
        self,
        file: str,
        start: dict[str, int],
        end: dict[str, int],
        only: list[str] | None = None,
        diagnostics: list[dict[str, Any]] | None = None,
        timeout_ms: int | None = None,
    ) -> list[MergedCodeAction]:
        """Public entry point for the §11.1 two-stage code-action merge.

        1. Broadcast textDocument/codeAction across the pool (T2).
        2. Resolve every deferred candidate (T6 — this method).
        3. Group by normalized family (T3).
        4. Apply Stage-1 priority filter per family (T4).
        5. Apply Stage-2 dedup-by-equivalence per family (T5).
        6. Wrap each survivor as a ``MergedCodeAction`` with provenance
           and ``suppressed_alternatives`` (debug-only per §11.4).

        Note: §11.7 invariants (apply-clean / ast.parse / disabled-filter
        / workspace-boundary) are enforced in T7 by a wrapping method
        ``merge_and_validate_code_actions``; this method delivers the
        unvalidated merge.
        """
        cast_diagnostics = diagnostics or []
        broadcast_kwargs: dict[str, Any] = {
            "file": file,
            "start": start,
            "end": end,
            "only": only,
            "diagnostics": cast_diagnostics,
        }
        broadcast = await self.broadcast(
            method="textDocument/codeAction",
            kwargs=broadcast_kwargs,
            timeout_ms=timeout_ms,
        )

        # Flatten responses + resolve deferred actions in parallel per server.
        flat: list[tuple[str, dict[str, Any]]] = []
        for sid, resp in broadcast.responses.items():
            if not isinstance(resp, list):
                continue
            for raw in resp:
                if not isinstance(raw, dict):
                    continue
                flat.append((sid, raw))

        if flat:
            resolve_tasks = [self._resolve_if_needed(sid, a) for sid, a in flat]
            resolved_actions = await asyncio.gather(*resolve_tasks, return_exceptions=False)
            flat = [(sid, resolved) for (sid, _), resolved in zip(flat, resolved_actions)]

        # Bucket by normalized family.
        primary_diagnostic = cast_diagnostics[0] if cast_diagnostics else None
        quickfix_context = _classify_quickfix_context(primary_diagnostic) if primary_diagnostic else "other"
        buckets: dict[tuple[str, str | None], list[tuple[str, dict[str, Any]]]] = {}
        for sid, action in flat:
            raw_kind = action.get("kind") or ""
            family = _normalize_kind(raw_kind)
            ctx = quickfix_context if family == "quickfix" else None
            key = (family, ctx)
            buckets.setdefault(key, []).append((sid, action))

        # Two-stage merge per bucket.
        out: list[MergedCodeAction] = []
        debug = os.environ.get("O2_SCALPEL_DEBUG_MERGE") == "1"
        action_seq = 0
        for (family, ctx), bucket_candidates in buckets.items():
            # Stage 1: priority filter.
            stage1 = _apply_priority(bucket_candidates, family=family, quickfix_context=ctx)
            # Lower-priority drops (everything in bucket but not in stage1, excluding disabled).
            disabled_pairs = {id(a): (s, a) for s, a in bucket_candidates
                              if isinstance(a.get("disabled"), dict) and a["disabled"].get("reason")}
            kept_pairs = {id(a): (s, a) for s, a in stage1}
            lower_priority_drops: list[tuple[str, dict[str, Any]]] = [
                (s, a) for s, a in bucket_candidates
                if id(a) not in kept_pairs and id(a) not in disabled_pairs
            ]
            # Stage 2: dedup over the active winners (excluding disabled).
            active_winners = [(s, a) for s, a in stage1 if id(a) not in disabled_pairs]
            priority_for_family = _PRIORITY_TABLE.get((family, ctx), ())
            stage2 = _dedup(active_winners, priority=priority_for_family)
            # Build MergedCodeAction per winner.
            for sid, action, dropped in stage2:
                action_seq += 1
                action_id = action.get("data", {}).get("id") if isinstance(action.get("data"), dict) else None
                action_id = str(action_id) if action_id is not None else f"merge-{action_seq}"
                disabled_reason: str | None = None
                if isinstance(action.get("disabled"), dict):
                    disabled_reason = action["disabled"].get("reason")
                suppressed: list[SuppressedAlternative] = []
                if debug:
                    for drop_sid, drop_action, reason in dropped:
                        suppressed.append(SuppressedAlternative(
                            title=drop_action.get("title", ""),
                            provenance=drop_sid,
                            reason=cast(Literal["lower_priority", "duplicate_title", "duplicate_edit"], reason),
                        ))
                    for drop_sid, drop_action in lower_priority_drops:
                        suppressed.append(SuppressedAlternative(
                            title=drop_action.get("title", ""),
                            provenance=drop_sid,
                            reason="lower_priority",
                        ))
                provenance = sid if sid in (
                    "pylsp-rope", "pylsp-base", "basedpyright", "ruff", "pylsp-mypy", "rust-analyzer"
                ) else "pylsp-base"
                if isinstance(action.get("edit"), dict):
                    self._action_edits[action_id] = action["edit"]
                out.append(MergedCodeAction(
                    id=action_id,
                    title=action.get("title", ""),
                    kind=action.get("kind", ""),
                    disabled_reason=disabled_reason,
                    is_preferred=bool(action.get("isPreferred", False)),
                    provenance=provenance,  # type: ignore[arg-type]
                    suppressed_alternatives=suppressed,
                ))
            # Disabled candidates are also surfaced.
            for sid, action in disabled_pairs.values():
                action_seq += 1
                action_id = action.get("data", {}).get("id") if isinstance(action.get("data"), dict) else None
                action_id = str(action_id) if action_id is not None else f"merge-{action_seq}"
                provenance = sid if sid in (
                    "pylsp-rope", "pylsp-base", "basedpyright", "ruff", "pylsp-mypy", "rust-analyzer"
                ) else "pylsp-base"
                if isinstance(action.get("edit"), dict):
                    self._action_edits[action_id] = action["edit"]
                out.append(MergedCodeAction(
                    id=action_id,
                    title=action.get("title", ""),
                    kind=action.get("kind", ""),
                    disabled_reason=action["disabled"].get("reason"),
                    is_preferred=bool(action.get("isPreferred", False)),
                    provenance=provenance,  # type: ignore[arg-type]
                    suppressed_alternatives=[],
                ))
        return out

    async def merge_and_validate_code_actions(
        self,
        file: str,
        start: dict[str, int],
        end: dict[str, int],
        only: list[str] | None = None,
        diagnostics: list[dict[str, Any]] | None = None,
        timeout_ms: int | None = None,
        workspace_folders: list[str] | None = None,
        extra_paths: tuple[str, ...] = (),
        document_versions: dict[str, int] | None = None,
    ) -> tuple[list[MergedCodeAction], list[MergedCodeAction]]:
        """Merge + enforce §11.7 four invariants.

        Returns ``(auto_apply, surfaced_only)``:
          - ``auto_apply``: candidates that passed all four invariants and
            are safe for facades to apply directly.
          - ``surfaced_only``: candidates the LLM still sees but that did
            NOT pass an invariant — disabled-reason carriers, syntax-
            invalid candidates, out-of-workspace candidates, stale-
            version candidates. Invariant-failure reason recorded in
            the candidate's ``disabled_reason`` field.

        Per §11.7: invariant 3 (disabled.reason) is implemented as
        "preserved in surfaced; never auto-applied". Invariant 4 path
        filter is implemented per §11.8 atomically (any rejected path
        rejects the whole WorkspaceEdit).
        """
        ws_folders = workspace_folders or []
        # Parse env-var allowlist per Stage 1B convention.
        env_extra = os.environ.get("O2_SCALPEL_WORKSPACE_EXTRA_PATHS", "")
        extra_combined: tuple[str, ...] = tuple(extra_paths) + tuple(
            p for p in env_extra.split(":") if p
        )
        versions = document_versions or {}

        # Broadcast + resolve so we have access to the raw per-server
        # candidate set (priority fallback needs to peek beyond the
        # Stage-1 winner — when the Stage-1 winner fails an invariant,
        # the next-priority candidate gets a chance).
        cast_diagnostics = diagnostics or []
        broadcast_kwargs: dict[str, Any] = {
            "file": file,
            "start": start,
            "end": end,
            "only": only,
            "diagnostics": cast_diagnostics,
        }
        broadcast = await self.broadcast(
            method="textDocument/codeAction",
            kwargs=broadcast_kwargs,
            timeout_ms=timeout_ms,
        )

        flat: list[tuple[str, dict[str, Any]]] = []
        for sid, resp in broadcast.responses.items():
            if not isinstance(resp, list):
                continue
            for raw in resp:
                if not isinstance(raw, dict):
                    continue
                flat.append((sid, raw))
        if flat:
            resolve_tasks = [self._resolve_if_needed(sid, a) for sid, a in flat]
            resolved_actions = await asyncio.gather(*resolve_tasks, return_exceptions=False)
            flat = [(sid, resolved) for (sid, _), resolved in zip(flat, resolved_actions)]

        primary_diagnostic = cast_diagnostics[0] if cast_diagnostics else None
        quickfix_context = _classify_quickfix_context(primary_diagnostic) if primary_diagnostic else "other"
        buckets: dict[tuple[str, str | None], list[tuple[str, dict[str, Any]]]] = {}
        for sid, action in flat:
            raw_kind = action.get("kind") or ""
            family = _normalize_kind(raw_kind)
            ctx = quickfix_context if family == "quickfix" else None
            buckets.setdefault((family, ctx), []).append((sid, action))

        auto_apply: list[MergedCodeAction] = []
        surfaced: list[MergedCodeAction] = []
        action_seq = 0

        def _to_merged(sid: str, action: dict[str, Any], reason: str | None) -> MergedCodeAction:
            nonlocal action_seq
            action_seq += 1
            raw_id = action.get("data", {}).get("id") if isinstance(action.get("data"), dict) else None
            aid = str(raw_id) if raw_id is not None else f"merge-{action_seq}"
            provenance = sid if sid in (
                "pylsp-rope", "pylsp-base", "basedpyright", "ruff", "pylsp-mypy", "rust-analyzer"
            ) else "pylsp-base"
            disabled_reason: str | None = reason
            if disabled_reason is None and isinstance(action.get("disabled"), dict):
                disabled_reason = action["disabled"].get("reason")
            if isinstance(action.get("edit"), dict):
                self._action_edits[aid] = action["edit"]
            return MergedCodeAction(
                id=aid,
                title=action.get("title", ""),
                kind=action.get("kind", ""),
                disabled_reason=disabled_reason,
                is_preferred=bool(action.get("isPreferred", False)),
                provenance=provenance,  # type: ignore[arg-type]
                suppressed_alternatives=[],
            )

        for (family, ctx), bucket_candidates in buckets.items():
            # Partition disabled vs active.
            disabled_pairs = [
                (s, a) for s, a in bucket_candidates
                if isinstance(a.get("disabled"), dict) and a["disabled"].get("reason")
            ]
            active = [
                (s, a) for s, a in bucket_candidates
                if not (isinstance(a.get("disabled"), dict) and a["disabled"].get("reason"))
            ]
            # Always surface disabled candidates.
            for sid, action in disabled_pairs:
                surfaced.append(_to_merged(sid, action, None))

            if not active:
                continue

            priority = _PRIORITY_TABLE.get((family, ctx), ())
            # Sort active by priority (winner-first).
            def _rank(sid: str, _priority: tuple[str, ...] = priority) -> int:
                try:
                    return _priority.index(sid)
                except ValueError:
                    return len(_priority)
            ordered = sorted(active, key=lambda sa: _rank(sa[0]))

            # Walk priority list; first candidate that passes invariants
            # becomes the auto-apply winner. All others (failed winners +
            # lower-priority equivalents) go to surfaced.
            chosen_idx: int | None = None
            chosen_failures: list[tuple[int, str]] = []
            for i, (sid, action) in enumerate(ordered):
                edit = action.get("edit") if isinstance(action.get("edit"), dict) else None
                if edit is None:
                    chosen_failures.append((i, "NO_EDIT"))
                    continue
                ok1, r1 = _check_apply_clean(edit, versions)
                ok2, r2 = _check_syntactic_validity(edit)
                ok4, r4 = _check_workspace_boundary(edit, ws_folders, extra_combined)
                if ok1 and ok2 and ok4:
                    chosen_idx = i
                    break
                chosen_failures.append((i, r1 or r2 or r4 or "INVARIANT_FAIL"))

            if chosen_idx is not None:
                # Auto-apply the winner; surface the failed earlier-priority
                # candidates with their failure reason.
                winner_sid, winner_action = ordered[chosen_idx]
                for fail_idx, fail_reason in chosen_failures:
                    fail_sid, fail_action = ordered[fail_idx]
                    surfaced.append(_to_merged(fail_sid, fail_action, fail_reason))
                auto_apply.append(_to_merged(winner_sid, winner_action, None))
            else:
                # All failed → surface them all.
                for fail_idx, fail_reason in chosen_failures:
                    fail_sid, fail_action = ordered[fail_idx]
                    surfaced.append(_to_merged(fail_sid, fail_action, fail_reason))

        return auto_apply, surfaced

    async def merge_rename(
        self,
        relative_file_path: str,
        line: int,
        column: int,
        new_name: str,
        language: str = "python",
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """Per §11.3, rename is single-primary per language.

        Python primary is pylsp-rope. When ``O2_SCALPEL_DEBUG_MERGE=1``,
        also call basedpyright and emit a ``provenance.disagreement``
        warning carrying the P6-shape symdiff summary; whole-file vs
        surgical edits are reconciled to a common surgical form via
        ``difflib`` line-mapping before the diff.

        Returns ``(workspace_edit_or_none, warnings)``.
        """
        primary_id = _RENAME_PRIMARY_BY_LANGUAGE.get(language)
        if primary_id is None or primary_id not in self._servers:
            return None, []
        primary = self._servers[primary_id]
        primary_edit = await primary.request_rename_symbol_edit(
            relative_file_path=relative_file_path,
            line=line,
            column=column,
            new_name=new_name,
        )
        if primary_edit is None:
            return None, []

        warnings: list[dict[str, Any]] = []
        if os.environ.get("O2_SCALPEL_DEBUG_MERGE") == "1":
            secondary_id = "basedpyright" if primary_id == "pylsp-rope" else None
            if secondary_id and secondary_id in self._servers:
                secondary = self._servers[secondary_id]
                try:
                    secondary_edit = await secondary.request_rename_symbol_edit(
                        relative_file_path=relative_file_path,
                        line=line,
                        column=column,
                        new_name=new_name,
                    )
                except Exception as exc:  # noqa: BLE001
                    warnings.append({
                        "kind": "provenance.disagreement",
                        "winner": primary_id,
                        "loser": secondary_id,
                        "loser_error": f"{type(exc).__name__}: {exc}",
                        "loser_returned_none": False,
                    })
                    return primary_edit, warnings
                if secondary_edit is None:
                    warnings.append({
                        "kind": "provenance.disagreement",
                        "winner": primary_id,
                        "loser": secondary_id,
                        "loser_returned_none": True,
                    })
                else:
                    def _read_unified(uri: str) -> str:
                        try:
                            return _uri_to_path(uri).read_text(encoding="utf-8")
                        except (FileNotFoundError, OSError):
                            return ""
                    symdiff = _rename_symdiff(primary_edit, secondary_edit, _read_unified)
                    warnings.append({
                        "kind": "provenance.disagreement",
                        "winner": primary_id,
                        "loser": secondary_id,
                        "loser_returned_none": False,
                        "symdiff": symdiff,
                    })
        return primary_edit, warnings

    async def find_symbol_position(
        self,
        file: str,
        name_path: str,
        project_root: str | None = None,
    ) -> dict[str, int] | None:
        """Resolve ``name_path`` to an LSP position via document symbols.

        Backlog #3 (v0.2.0). Walks ``request_document_symbols`` hierarchically
        by name_path segments — split on ``::`` (Rust) and ``.`` (Python).
        Falls back to ``request_workspace_symbol`` with the last segment when
        the document-level walk misses, filtering hits by ``file`` URI.

        Returns ``{"line": int, "character": int}`` of the symbol's selection
        range start, or ``None`` if no match is found across all servers.
        """
        if not self._servers:
            return None
        segments = _split_name_path(name_path)
        if not segments:
            return None
        rel_path = _to_relative_path(file, project_root)
        for server in self._servers.values():
            doc_symbols = await asyncio.to_thread(
                server.request_document_symbols, rel_path,
            )
            pos = _walk_document_symbols(doc_symbols, segments)
            if pos is not None:
                return pos
        # Document-level walk missed — try workspace_symbol scoped to file.
        target_uri = Path(file).as_uri()
        for server in self._servers.values():
            ws_results = await asyncio.to_thread(
                server.request_workspace_symbol, segments[-1],
            )
            if not ws_results:
                continue
            for hit in ws_results:
                loc = hit.get("location") or {}
                if loc.get("uri") != target_uri:
                    continue
                start = (loc.get("range") or {}).get("start") or {}
                if "line" in start and "character" in start:
                    return {
                        "line": int(start["line"]),
                        "character": int(start["character"]),
                    }
        return None

    async def expand_macro(
        self,
        file: str,
        position: dict[str, int],
    ) -> dict[str, Any] | None:
        """Stage 3 — fan ``rust-analyzer/expandMacro`` to the rust-analyzer server.

        Returns the first server's response (single-server method); ``None``
        when the rust-analyzer server isn't in the pool or returned nothing.
        """
        server = self._servers.get("rust-analyzer")
        if server is None:
            return None
        fn = getattr(server, "expand_macro", None)
        if fn is None:
            return None
        result = await asyncio.to_thread(fn, file, position)
        return result if isinstance(result, dict) else None

    async def fetch_runnables(
        self,
        file: str,
        position: dict[str, int] | None = None,
    ) -> list[dict[str, Any]]:
        """Stage 3 — fan ``experimental/runnables`` to the rust-analyzer server."""
        server = self._servers.get("rust-analyzer")
        if server is None:
            return []
        fn = getattr(server, "fetch_runnables", None)
        if fn is None:
            return []
        result = await asyncio.to_thread(fn, file, position)
        return list(result) if isinstance(result, list) else []

    async def run_flycheck(
        self,
        file: str,
    ) -> dict[str, Any]:
        """Stage 3 — fan ``rust-analyzer/runFlycheck`` to the rust-analyzer server."""
        server = self._servers.get("rust-analyzer")
        if server is None:
            return {"diagnostics": []}
        fn = getattr(server, "run_flycheck", None)
        if fn is None:
            return {"diagnostics": []}
        result = await asyncio.to_thread(fn, file)
        return result if isinstance(result, dict) else {"diagnostics": []}


def _split_name_path(name_path: str) -> list[str]:
    """Split ``name_path`` on ``::`` (Rust) and ``.`` (Python) separators."""
    if not name_path:
        return []
    pieces: list[str] = []
    for cc in name_path.split("::"):
        for dotted in cc.split("."):
            if dotted:
                pieces.append(dotted)
    return pieces


def _to_relative_path(file: str, project_root: str | None) -> str:
    """Return ``file`` made relative to ``project_root`` when possible."""
    if project_root is None:
        return file
    try:
        return str(Path(file).relative_to(project_root))
    except ValueError:
        return file


def _walk_document_symbols(
    nodes: Any, segments: list[str],
) -> dict[str, int] | None:
    """Walk the LSP document-symbol tree, matching ``segments`` head-first."""
    if not segments:
        return None
    head, rest = segments[0], segments[1:]
    iterable = nodes if isinstance(nodes, (list, tuple)) else [nodes]
    for node in iterable:
        if not isinstance(node, dict):
            continue
        if node.get("name") != head:
            continue
        if not rest:
            sel = node.get("selectionRange") or node.get("range") or {}
            start = sel.get("start") or {}
            if "line" in start and "character" in start:
                return {
                    "line": int(start["line"]),
                    "character": int(start["character"]),
                }
            return None
        children = node.get("children") or []
        deeper = _walk_document_symbols(children, rest)
        if deeper is not None:
            return deeper
    return None


class EditAttributionLog:
    """Append-only JSONL log of every applied WorkspaceEdit per §11.5.

    Schema (one record per line):
        {"ts": ISO8601 UTC, "checkpoint_id": str, "tool": str, "server": str,
         "kind": "TextDocumentEdit"|"CreateFile"|"RenameFile"|"DeleteFile",
         "uri": str, "edit_count": int, "version": int|None}

    Idempotent — replaying the log replays the exact session per §11.5.
    Writes serialise through ``self._lock`` so concurrent appends cannot
    interleave bytes within a JSONL line.
    """

    def __init__(self, project_root: Path) -> None:
        self._project_root = Path(project_root)
        self._lock = asyncio.Lock()

    @property
    def path(self) -> Path:
        return self._project_root / ".serena" / "python-edit-log.jsonl"

    async def append(
        self,
        *,
        checkpoint_id: str,
        tool: str,
        server: str,
        edit: dict[str, Any],
    ) -> None:
        """Append one record per ``documentChanges`` entry in ``edit``.

        Multi-entry WorkspaceEdits emit one log line per entry so replay
        forensics can map each line to a single LSP operation.
        """
        records = list(self._records_from_edit(checkpoint_id, tool, server, edit))
        if not records:
            return
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                for rec in records:
                    fh.write(json.dumps(rec, separators=(",", ":")) + "\n")

    def replay(self) -> Iterator[dict[str, Any]]:
        """Yield every record in append order. Empty when the log is missing."""
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                yield json.loads(line)

    @staticmethod
    def _records_from_edit(
        checkpoint_id: str, tool: str, server: str, edit: dict[str, Any]
    ) -> Iterator[dict[str, Any]]:
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        for change in edit.get("documentChanges", []) or []:
            kind_field = change.get("kind")
            if kind_field == "create":
                yield {
                    "ts": ts, "checkpoint_id": checkpoint_id, "tool": tool, "server": server,
                    "kind": "CreateFile", "uri": change["uri"],
                    "edit_count": 0, "version": None,
                }
            elif kind_field == "rename":
                yield {
                    "ts": ts, "checkpoint_id": checkpoint_id, "tool": tool, "server": server,
                    "kind": "RenameFile", "uri": change["newUri"],
                    "edit_count": 0, "version": None,
                }
            elif kind_field == "delete":
                yield {
                    "ts": ts, "checkpoint_id": checkpoint_id, "tool": tool, "server": server,
                    "kind": "DeleteFile", "uri": change["uri"],
                    "edit_count": 0, "version": None,
                }
            else:
                # Default: TextDocumentEdit shape.
                td = change.get("textDocument", {})
                edits = change.get("edits", []) or []
                yield {
                    "ts": ts, "checkpoint_id": checkpoint_id, "tool": tool, "server": server,
                    "kind": "TextDocumentEdit", "uri": td.get("uri", ""),
                    "edit_count": len(edits), "version": td.get("version"),
                }


__all__ = [
    "EditAttributionLog",
    "MergedCodeAction",
    "MultiServerBroadcastResult",
    "MultiServerCoordinator",
    "ProvenanceLiteral",
    "ServerTimeoutWarning",
    "SuppressedAlternative",
]
