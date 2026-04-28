"""DLp2 — unit tests for ``solidlsp.capability_keys``.

Spec reference: dynamic LSP capability spec § 4.4.3 + § 7 / test_capability_keys.py.

Verifies:
1. All symbolic constants are non-empty strings.
2. ``_METHOD_TO_PROVIDER_KEY`` covers every method string referenced by
   the facades (hard-coded expected set derived from the spec table).
3. The table maps to correct ``ServerCapabilities`` provider field names.
"""

from __future__ import annotations

import pytest

from solidlsp.capability_keys import (
    CODE_ACTION,
    COMPLETION,
    DOCUMENT_LINK,
    DOCUMENT_SYMBOL,
    EXECUTE_COMMAND,
    FOLDING_RANGE,
    GO_TO_DEFINITION,
    GO_TO_IMPLEMENTATION,
    GO_TO_REFERENCES,
    HOVER,
    INLAY_HINT,
    PREPARE_RENAME,
    RENAME,
    WORKSPACE_SYMBOL,
    _METHOD_TO_PROVIDER_KEY,
)


# ---------------------------------------------------------------------------
# Symbolic constant smoke tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method",
    [
        GO_TO_DEFINITION,
        GO_TO_IMPLEMENTATION,
        GO_TO_REFERENCES,
        RENAME,
        PREPARE_RENAME,
        CODE_ACTION,
        EXECUTE_COMMAND,
        HOVER,
        COMPLETION,
        DOCUMENT_SYMBOL,
        WORKSPACE_SYMBOL,
        DOCUMENT_LINK,
        FOLDING_RANGE,
        INLAY_HINT,
    ],
)
def test_constant_is_nonempty_string(method: str) -> None:
    """Every constant must be a non-empty string."""
    assert isinstance(method, str)
    assert len(method) > 0


def test_constants_have_namespace_prefix() -> None:
    """All method constants follow the LSP textDocument/* or workspace/* pattern."""
    for const in [
        GO_TO_DEFINITION, GO_TO_IMPLEMENTATION, GO_TO_REFERENCES,
        RENAME, PREPARE_RENAME, CODE_ACTION, HOVER, DOCUMENT_SYMBOL,
        DOCUMENT_LINK, FOLDING_RANGE, INLAY_HINT, COMPLETION,
    ]:
        assert const.startswith("textDocument/"), f"{const!r} must start with 'textDocument/'"

    for const in [EXECUTE_COMMAND, WORKSPACE_SYMBOL]:
        assert const.startswith("workspace/"), f"{const!r} must start with 'workspace/'"


# ---------------------------------------------------------------------------
# _METHOD_TO_PROVIDER_KEY table coverage
# ---------------------------------------------------------------------------


# Minimum expected entries per spec § 4.4.3 + facade usage audit.
_REQUIRED_ENTRIES: dict[str, str] = {
    "textDocument/implementation": "implementationProvider",
    "textDocument/definition": "definitionProvider",
    "textDocument/references": "referencesProvider",
    "textDocument/codeAction": "codeActionProvider",
    "textDocument/rename": "renameProvider",
    "textDocument/prepareRename": "renameProvider",
    "textDocument/inlayHint": "inlayHintProvider",
    "textDocument/foldingRange": "foldingRangeProvider",
    "textDocument/documentSymbol": "documentSymbolProvider",
    "textDocument/hover": "hoverProvider",
    "workspace/symbol": "workspaceSymbolProvider",
    "workspace/executeCommand": "executeCommandProvider",
}


@pytest.mark.parametrize("method,expected_key", list(_REQUIRED_ENTRIES.items()))
def test_method_maps_to_expected_provider_key(method: str, expected_key: str) -> None:
    """Each required method maps to the exact ServerCapabilities field name."""
    assert _METHOD_TO_PROVIDER_KEY.get(method) == expected_key, (
        f"_METHOD_TO_PROVIDER_KEY[{method!r}] should be {expected_key!r}"
    )


def test_table_covers_all_required_entries() -> None:
    """The table is a superset of the required entries (never shrinks)."""
    missing = set(_REQUIRED_ENTRIES) - set(_METHOD_TO_PROVIDER_KEY)
    assert not missing, f"_METHOD_TO_PROVIDER_KEY is missing entries: {missing}"


def test_provider_keys_are_camel_case_provider_suffix() -> None:
    """All provider values end with 'Provider' per LSP ServerCapabilities naming."""
    for method, key in _METHOD_TO_PROVIDER_KEY.items():
        assert key.endswith("Provider"), (
            f"Provider key for {method!r} should end with 'Provider', got {key!r}"
        )


def test_symbolic_constants_match_table_keys() -> None:
    """Symbolic constants equal the corresponding table keys."""
    assert _METHOD_TO_PROVIDER_KEY.get(GO_TO_IMPLEMENTATION) == "implementationProvider"
    assert _METHOD_TO_PROVIDER_KEY.get(GO_TO_DEFINITION) == "definitionProvider"
    assert _METHOD_TO_PROVIDER_KEY.get(GO_TO_REFERENCES) == "referencesProvider"
    assert _METHOD_TO_PROVIDER_KEY.get(CODE_ACTION) == "codeActionProvider"
    assert _METHOD_TO_PROVIDER_KEY.get(RENAME) == "renameProvider"
    assert _METHOD_TO_PROVIDER_KEY.get(PREPARE_RENAME) == "renameProvider"
    assert _METHOD_TO_PROVIDER_KEY.get(INLAY_HINT) == "inlayHintProvider"
    assert _METHOD_TO_PROVIDER_KEY.get(FOLDING_RANGE) == "foldingRangeProvider"
    assert _METHOD_TO_PROVIDER_KEY.get(DOCUMENT_SYMBOL) == "documentSymbolProvider"
    assert _METHOD_TO_PROVIDER_KEY.get(HOVER) == "hoverProvider"
    assert _METHOD_TO_PROVIDER_KEY.get(WORKSPACE_SYMBOL) == "workspaceSymbolProvider"
    assert _METHOD_TO_PROVIDER_KEY.get(EXECUTE_COMMAND) == "executeCommandProvider"
