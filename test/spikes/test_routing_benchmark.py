"""v1.5 Phase 1 — routing benchmark scorer.

Spec: docs/superpowers/specs/2026-04-29-lsp-feature-coverage-spec.md § 3.4.

Deterministic, offline, no Claude API call. The scorer iterates each prompt
in ``data/routing_benchmark.json`` (10 prompts × 3 trials each = 30 trials),
computes a keyword-overlap similarity ranking against every registered
``scalpel_*`` facade docstring, and asserts the expected tool ranks first.

Reports a single percentage: ``routing_accuracy = correct_top_1 / total``.
The keyword-overlap scorer is sufficient for v1.5 (semantic-embedding
ranking is a Phase 4-era upgrade per spec § 8 risks).

The harness pattern follows existing ``test/spikes/`` deterministic tests
(e.g. ``test_apply_source_determinism.py``).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest

import serena.tools as tools_module

SPIKE_DATA = Path(__file__).resolve().parent / "data"
BENCHMARK_PATH = SPIKE_DATA / "routing_benchmark.json"

# Routing-accuracy floor for v1.5. Phase 4 gate (spec § 4.5) requires a
# +10pp uplift over this floor for any horizontal facade expansion.
# 0.50 = "scoring better than coin-flip on 10-tool ranking is non-trivial"
# Empirical baseline measured in this run is recorded in the Phase 1
# release notes (spec § 3.5 exit criterion).
MIN_ROUTING_ACCURACY = 0.50

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+")
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at",
    "for", "with", "by", "from", "into", "this", "that", "these", "those",
    "is", "are", "was", "were", "be", "been", "being",
    "it", "its", "as", "if", "then", "than", "so", "not",
    "preferred", "fallback", "args", "returns", "via", "lsp", "tool",
})


def _tokenize(text: str) -> Counter[str]:
    """Lowercase keyword bag, stopwords removed."""
    return Counter(
        t.lower() for t in _TOKEN_RE.findall(text)
        if t.lower() not in _STOPWORDS and len(t) > 1
    )


def _gather_facade_docstrings() -> dict[str, str]:
    """Collect every ``Scalpel*Tool`` class docstring keyed by canonical
    snake_case tool name (the name surfaced via MCP).

    Names follow the existing convention: ``ScalpelExtractTool`` -> ``scalpel_extract``.
    """
    docs: dict[str, str] = {}
    seen_classes: set[type] = set()
    for attr_name in dir(tools_module):
        if not attr_name.startswith("Scalpel"):
            continue
        cls = getattr(tools_module, attr_name)
        if not isinstance(cls, type) or cls in seen_classes:
            continue
        seen_classes.add(cls)
        if not attr_name.endswith("Tool"):
            continue
        canonical = _classname_to_tool_name(attr_name)
        doc = (cls.__doc__ or "").strip()
        if doc:
            docs[canonical] = doc
    return docs


def _classname_to_tool_name(class_name: str) -> str:
    """``ScalpelExtractTool`` -> ``scalpel_extract``."""
    stripped = class_name[: -len("Tool")] if class_name.endswith("Tool") else class_name
    out: list[str] = []
    for i, ch in enumerate(stripped):
        if ch.isupper() and i > 0:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def _score_prompt(prompt: str, docs: dict[str, str]) -> list[tuple[str, float]]:
    """Rank facade names by Jaccard-like keyword overlap with ``prompt``.

    Returns descending-score list of ``(tool_name, score)``.
    """
    prompt_tokens = _tokenize(prompt)
    if not prompt_tokens:
        return []
    ranked: list[tuple[str, float]] = []
    for tool, doc in docs.items():
        doc_tokens = _tokenize(doc)
        # Bonus: tool name itself contributes lexical signal — lowering
        # it through to the scorer means a prompt that says "extract"
        # naturally lifts ``scalpel_extract`` regardless of docstring text.
        name_tokens = Counter(tool.split("_"))
        bag = doc_tokens + name_tokens
        if not bag:
            continue
        overlap = sum(min(prompt_tokens[t], bag[t]) for t in prompt_tokens)
        union = sum((prompt_tokens | bag).values())
        score = overlap / union if union else 0.0
        ranked.append((tool, score))
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked


def _trials() -> list[tuple[str, str]]:
    """Yield ``(prompt_text, expected_tool)`` for every entry × paraphrase."""
    payload = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    out: list[tuple[str, str]] = []
    for entry in payload["entries"]:
        out.append((entry["prompt"], entry["expected_tool"]))
        for p in entry.get("paraphrases", []):
            out.append((p, entry["expected_tool"]))
    return out


def test_routing_benchmark_fixture_exists() -> None:
    assert BENCHMARK_PATH.exists()
    payload = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    # 10 entries × (1 base prompt + 2 paraphrases) = 30 trials
    assert len(_trials()) == 30, f"expected 30 trials, got {len(_trials())}"


def test_facade_docstrings_loadable() -> None:
    docs = _gather_facade_docstrings()
    # v1.5 ships ~33 scalpel facades. Loose lower bound to stay robust
    # against future additions.
    assert len(docs) >= 20, f"only {len(docs)} facade docstrings discoverable"


@pytest.mark.parametrize(("prompt", "expected"), _trials())
def test_routing_benchmark_per_trial(prompt: str, expected: str) -> None:
    """Per-trial smoke: scorer runs and returns a ranking. Per-prompt
    strict top-1 / top-3 is intentionally NOT asserted here.

    Per spec § 3.4, v1.5 is the *baseline-recording* run; the docstring
    quality lift that drives top-1 accuracy is Phase 3's job (the
    PREFERRED:/FALLBACK: convention). Asserting top-N per-trial in v1.5
    would conflate Phase-1 instrumentation with Phase-3 lift and break
    the empirical chain the §4.5 Phase-4 gate depends on.

    The aggregate ``routing_accuracy`` floor is asserted in
    ``test_routing_accuracy_meets_floor`` below.
    """
    docs = _gather_facade_docstrings()
    if expected not in docs:
        pytest.skip(f"expected tool {expected!r} not registered (host gap)")
    ranked = _score_prompt(prompt, docs)
    assert ranked, f"scorer returned empty ranking for {prompt!r}"


def test_routing_accuracy_meets_floor() -> None:
    """Aggregate routing_accuracy = correct_top_1 / total_prompts.

    Asserts the v1.5 floor (50%); the actual measured value is printed
    so the Phase 1 release notes can record the empirical baseline.
    """
    docs = _gather_facade_docstrings()
    trials = _trials()
    skipped = 0
    correct_top1 = 0
    total = 0
    for prompt, expected in trials:
        if expected not in docs:
            skipped += 1
            continue
        total += 1
        ranked = _score_prompt(prompt, docs)
        if ranked and ranked[0][0] == expected:
            correct_top1 += 1
    accuracy = correct_top1 / total if total else 0.0
    print(
        f"\nrouting_accuracy={accuracy:.3f} "
        f"(correct_top_1={correct_top1}, total={total}, skipped={skipped})"
    )
    assert accuracy >= MIN_ROUTING_ACCURACY, (
        f"routing_accuracy={accuracy:.3f} fell below floor "
        f"{MIN_ROUTING_ACCURACY:.3f}; review prompts or facade docstrings"
    )
