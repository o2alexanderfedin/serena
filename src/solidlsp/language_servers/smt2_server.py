"""SMT-LIB v2 LSP adapter — Stream 6 / Leaf F (v1.4.1: dolmenls-backed).

SMT-LIB 2 (https://smtlib.cs.uiowa.edu/) is the standard input language for
Satisfiability Modulo Theories (SMT) solvers such as Z3, CVC5, and Yices.
Files use ``.smt2`` (canonical) or ``.smt`` extensions.

**Backend (v1.4.1):** `dolmenls`_, the language server shipped from the
`Dolmen`_ monorepo (Guillaume Bury). Dolmenls is a diagnostics-focused LSP:
it parses, sort-checks, and reports errors over `textDocument/publishDiagnostics`.
Hover / goto-definition / references / rename / formatting are NOT implemented
upstream as of v0.10 — the runtime
:class:`~solidlsp.dynamic_capabilities.DynamicCapabilityRegistry` gates these
honestly per session.

.. _dolmenls: https://github.com/Gbury/dolmen/blob/master/doc/lsp.md
.. _Dolmen: https://github.com/Gbury/dolmen

**Capability surface:**

SMT-LIB 2 is a **constraint specification format**, not a general-purpose
programming language.  Refactoring operations (rename, extract) have no
well-defined semantics at the solver level — renaming a sort or function
symbol across a multi-file benchmark suite requires solver-aware dependency
tracking that dolmen does not currently provide.  The strategy therefore
advertises ``quickfix`` only — diagnostic-driven auto-corrections such as
syntax fixes or sort-mismatch suggestions surfaced by dolmenls.

Binary entry point: ``dolmenls`` (bare; stdio transport; no required args).
Install: see :class:`~serena.installer.smt2_installer.Smt2Installer` — pulls
pre-built binaries (``dolmenls-{linux,macos,windows}-amd64``) from the
``Gbury/dolmen`` GitHub Releases (pinned to v0.10).
"""

from __future__ import annotations

import logging
import os
import pathlib
import shutil
from typing import Any, ClassVar, cast

from overrides import override

from solidlsp.ls import SolidLanguageServer
from solidlsp.ls_config import Language, LanguageServerConfig
from solidlsp.lsp_protocol_handler.lsp_types import InitializeParams
from solidlsp.lsp_protocol_handler.server import ProcessLaunchInfo
from solidlsp.settings import SolidLSPSettings

log = logging.getLogger(__name__)

# Real binary as of v1.4.1: dolmenls from Gbury/dolmen (v0.10 pin).
# The Smt2Installer pulls platform-tagged binaries from GitHub Releases.
_SMT2_LSP_BINARY = "dolmenls"


class Smt2Server(SolidLanguageServer):
    """SMT-LIB 2 LSP adapter backed by ``dolmenls`` (v1.4.1).

    Dolmenls is diagnostics-focused: parses, sort-checks, and emits
    ``textDocument/publishDiagnostics``. Other LSP methods are gated at
    runtime by :class:`~solidlsp.dynamic_capabilities.DynamicCapabilityRegistry`
    based on the ``ServerCapabilities`` returned at initialize.

    Capability surface advertised here is permissive (definition / references /
    hover / documentSymbol) so that the static catalog tracks dolmenls's
    aspirational evolution; the dynamic registry filters per session.
    Code-action kinds are restricted to ``quickfix`` — SMT-LIB has no
    solver-level rename/extract semantics regardless of LSP capability.
    """

    server_id: ClassVar[str] = "dolmenls"

    def __init__(
        self,
        config: LanguageServerConfig,
        repository_root_path: str,
        solidlsp_settings: SolidLSPSettings,
    ) -> None:
        binary = shutil.which(_SMT2_LSP_BINARY)
        if binary is None:
            log.debug(
                "%s binary not on PATH; spawn will fail — "
                "install via Smt2Installer (scalpel_install_lsp_servers).",
                _SMT2_LSP_BINARY,
            )
            binary = _SMT2_LSP_BINARY  # nominal — start_server will surface the failure
        # dolmenls speaks LSP over stdio with no required args.
        super().__init__(
            config,
            repository_root_path,
            ProcessLaunchInfo(
                cmd=binary,
                cwd=repository_root_path,
            ),
            "smt2",
            solidlsp_settings,
        )

    @classmethod
    @override
    def get_language_enum_instance(cls) -> Language:
        return Language.SMT2

    @override
    def is_ignored_dirname(self, dirname: str) -> bool:
        return super().is_ignored_dirname(dirname) or dirname in (
            ".z3",    # Z3 temporary / cache directories
            ".cvc5",  # CVC5 temporary / cache directories
        )

    @staticmethod
    def _get_initialize_params(repository_absolute_path: str) -> InitializeParams:
        """SMT-LIB 2 initialize-params: quickfix code actions only.

        The params are pre-wired for a future SMT2 LSP that follows the
        standard LSP code-action protocol.  The ``quickfix`` kind covers
        diagnostic-driven auto-corrections (e.g. sort-mismatch fixes,
        missing assertion guards).

        No ``refactor.*`` kinds are advertised — SMT-LIB 2 has no
        well-defined rename/extract semantics at the solver level.
        """
        root_uri = pathlib.Path(repository_absolute_path).as_uri()
        params: dict[str, Any] = {
            "processId": os.getpid(),
            "clientInfo": {"name": "Serena", "version": "0.1.0"},
            "locale": "en",
            "rootPath": repository_absolute_path,
            "rootUri": root_uri,
            "capabilities": {
                "workspace": {
                    "applyEdit": True,
                    "workspaceEdit": {
                        "documentChanges": True,
                        "resourceOperations": ["create", "rename", "delete"],
                        "failureHandling": "textOnlyTransactional",
                    },
                    "configuration": True,
                    "didChangeConfiguration": {"dynamicRegistration": True},
                    "workspaceFolders": True,
                    "symbol": {"dynamicRegistration": True},
                },
                "textDocument": {
                    "synchronization": {
                        "dynamicRegistration": True,
                        "willSave": False,
                        "willSaveWaitUntil": False,
                        "didSave": True,
                    },
                    "completion": {
                        "dynamicRegistration": True,
                        "completionItem": {
                            "snippetSupport": True,
                            "documentationFormat": ["markdown", "plaintext"],
                        },
                    },
                    "definition": {"dynamicRegistration": True, "linkSupport": True},
                    "references": {"dynamicRegistration": True},
                    "hover": {
                        "dynamicRegistration": True,
                        "contentFormat": ["markdown", "plaintext"],
                    },
                    "documentSymbol": {
                        "dynamicRegistration": True,
                        "hierarchicalDocumentSymbolSupport": True,
                        "symbolKind": {"valueSet": list(range(1, 27))},
                    },
                    "foldingRange": {"dynamicRegistration": True},
                    "codeAction": {
                        "dynamicRegistration": True,
                        "codeActionLiteralSupport": {
                            "codeActionKind": {
                                "valueSet": [
                                    # Diagnostic-driven auto-corrections.
                                    # The only kind safe for a constraint
                                    # specification format — no rename/extract
                                    # because SMT-LIB has no rename semantics
                                    # at the solver level.
                                    "quickfix",
                                ],
                            },
                        },
                        "resolveSupport": {"properties": ["edit"]},
                    },
                    "publishDiagnostics": {
                        "relatedInformation": True,
                        "tagSupport": {"valueSet": [1, 2]},
                    },
                },
            },
            "workspaceFolders": [
                {"uri": root_uri, "name": pathlib.Path(repository_absolute_path).name}
            ],
        }
        return cast(InitializeParams, params)

    def _start_server(self) -> None:
        """Boot the SMT2 LSP: register handlers, start subprocess, initialize."""

        def register_capability_handler(_params: dict) -> None:
            return

        def workspace_configuration_handler(params: dict) -> list[dict] | dict:
            if "items" in params:
                return [{}] * len(params["items"])
            return {}

        def window_log_message(msg: dict) -> None:
            log.info("LSP: window/logMessage: %s", msg)

        def do_nothing(_params: dict) -> None:
            return

        self.server.on_request("client/registerCapability", register_capability_handler)
        self.server.on_request("workspace/configuration", workspace_configuration_handler)
        self.server.on_notification("window/logMessage", window_log_message)
        self.server.on_notification("$/progress", do_nothing)
        self.server.on_notification("textDocument/publishDiagnostics", do_nothing)

        log.info("Starting %s process", _SMT2_LSP_BINARY)
        self.server.start()
        initialize_params = self._get_initialize_params(self.repository_root_path)

        log.info("Sending initialize request to %s", _SMT2_LSP_BINARY)
        init_response = self.server.send.initialize(initialize_params)
        log.debug("%s initialize response: %s", _SMT2_LSP_BINARY, init_response)

        caps = init_response["capabilities"]
        assert "textDocumentSync" in caps, (
            f"{_SMT2_LSP_BINARY} did not advertise textDocumentSync"
        )

        self.server.notify.initialized({})
        log.info("%s initialization complete", _SMT2_LSP_BINARY)
