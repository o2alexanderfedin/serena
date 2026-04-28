"""Symbolic constants for LSP method strings and the method → ServerCapabilities
provider-field mapping table.

Centralising these here:
  - eliminates magic strings scattered across callers,
  - makes the mapping exhaustive and auditable in one place,
  - mirrors the ``_request_name_to_server_capability`` table in Neovim's
    ``vim.lsp.util`` (landscape.md §2.3) and the VSCode capability-resolver
    in ``vscode-languageclient/lib/node/client.ts``.

See dynamic LSP capability spec § 4.4.3 for the authoritative source of the
``_METHOD_TO_PROVIDER_KEY`` table.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Symbolic method constants
# ---------------------------------------------------------------------------

GO_TO_DEFINITION = "textDocument/definition"
GO_TO_IMPLEMENTATION = "textDocument/implementation"
GO_TO_REFERENCES = "textDocument/references"
RENAME = "textDocument/rename"
PREPARE_RENAME = "textDocument/prepareRename"
CODE_ACTION = "textDocument/codeAction"
EXECUTE_COMMAND = "workspace/executeCommand"
HOVER = "textDocument/hover"
COMPLETION = "textDocument/completion"
DOCUMENT_SYMBOL = "textDocument/documentSymbol"
WORKSPACE_SYMBOL = "workspace/symbol"
DOCUMENT_LINK = "textDocument/documentLink"
FOLDING_RANGE = "textDocument/foldingRange"
INLAY_HINT = "textDocument/inlayHint"

# ---------------------------------------------------------------------------
# Method → ServerCapabilities provider-field table
#
# Both ``textDocument/rename`` and ``textDocument/prepareRename`` map to
# the same ``renameProvider`` field.  The ``supports_method`` predicate in
# ``MultiServerCoordinator`` handles the ``prepareRename`` sub-capability
# special case (inspects the options object for ``prepareProvider: bool``)
# as documented in spec § R5.
#
# Absent methods (e.g. custom ``rust-analyzer/*`` extensions) are not in
# this table; ``supports_method`` denies them by returning ``False`` for an
# unknown method.  Custom methods are handled via the per-server custom-method
# allowlist (spec § R7), which acts as a Tier-0 gate before this table.
# ---------------------------------------------------------------------------

_METHOD_TO_PROVIDER_KEY: dict[str, str] = {
    GO_TO_IMPLEMENTATION: "implementationProvider",
    GO_TO_DEFINITION: "definitionProvider",
    GO_TO_REFERENCES: "referencesProvider",
    CODE_ACTION: "codeActionProvider",
    RENAME: "renameProvider",
    # prepareRename shares the same provider field as rename;
    # supports_method applies extra sub-capability check for this case.
    PREPARE_RENAME: "renameProvider",
    INLAY_HINT: "inlayHintProvider",
    FOLDING_RANGE: "foldingRangeProvider",
    DOCUMENT_SYMBOL: "documentSymbolProvider",
    HOVER: "hoverProvider",
    WORKSPACE_SYMBOL: "workspaceSymbolProvider",
    EXECUTE_COMMAND: "executeCommandProvider",
}
