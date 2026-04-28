"""Prolog LSP adapter — Stream 6 / Leaf G.

Targets SWI-Prolog's community LSP server ``lsp_server``
(https://github.com/jamesnvc/lsp_server), installed as a SWI-Prolog pack.

SWI-Prolog (https://www.swi-prolog.org/) is the most widely used open-source
Prolog implementation.  The ``lsp_server`` pack provides an LSP endpoint
over stdio, exposing diagnostics (singleton variables, syntax errors),
find-definitions, find-references, hover documentation, auto-completion, and
variable renaming.

**Install (SWI-Prolog pack manager):**

  ``swipl -g "pack_install(lsp_server)" -t halt``

  Or from the SWI-Prolog REPL:
  ``?- pack_install(lsp_server).``

  Requires SWI-Prolog 8.1.5 or newer (earlier versions lack the
  ``find_references`` predicate used by the pack).

**Launch:**

  ``swipl -g "use_module(library(lsp_server))." \\
          -g "lsp_server:main" -t halt -- stdio``

  The ``--`` separator passes ``stdio`` as a positional argument to the
  lsp_server main/0 entry point, selecting the stdio transport over the
  default socket mode.

**Capability surface:**

  ``quickfix``  — diagnostic quick-fixes: singleton-variable warnings,
                  unused-import suggestions, syntax errors.

  ``refactor.rename``  — Prolog has clean predicate renaming semantics:
                         a predicate name is purely symbolic (no dependent
                         types, no proof context), so alpha-renaming across
                         the current file is safe.  The lsp_server pack
                         implements ``textDocument/rename`` for variable and
                         atom renaming.

No ``refactor.extract`` — extracting a goal into a separate predicate
requires understanding of the caller's binding context, which the current
lsp_server implementation does not provide.

Binary entry point: ``swipl``
Extensions: ``.pl``, ``.pro``, ``.prolog``
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

# SWI-Prolog binary — the lsp_server pack launches inside the swipl runtime.
_SWIPL_BINARY = "swipl"

# Launch arguments: load the lsp_server library, call its entry point,
# halt on exit, then pass stdio as the transport selector.
_SWIPL_LSP_ARGS = (
    "-g", "use_module(library(lsp_server)).",
    "-g", "lsp_server:main",
    "-t", "halt",
    "--", "stdio",
)


class PrologServer(SolidLanguageServer):
    """Prolog LSP adapter (SWI-Prolog + lsp_server pack).

    Targets the ``lsp_server`` SWI-Prolog pack by James Cash
    (https://github.com/jamesnvc/lsp_server).  The server is launched
    by invoking ``swipl`` with the pack's ``main/0`` entry point over stdio.

    Capability surface: ``quickfix`` + ``refactor.rename`` — Prolog predicates
    are purely symbolic names, making rename alpha-safe.  Extract is excluded
    because goal extraction requires binding-context analysis that the current
    pack does not provide.

    Install via SWI-Prolog pack manager:
      ``swipl -g "pack_install(lsp_server)" -t halt``
    """

    server_id: ClassVar[str] = "swipl-lsp"

    def __init__(
        self,
        config: LanguageServerConfig,
        repository_root_path: str,
        solidlsp_settings: SolidLSPSettings,
    ) -> None:
        binary = shutil.which(_SWIPL_BINARY)
        if binary is None:
            log.debug(
                "swipl binary not on PATH; spawn will fail until PrologInstaller runs"
            )
            binary = _SWIPL_BINARY  # nominal — start_server will surface the failure
        args_str = " ".join(_SWIPL_LSP_ARGS)
        super().__init__(
            config,
            repository_root_path,
            ProcessLaunchInfo(
                cmd=f"{binary} {args_str}",
                cwd=repository_root_path,
            ),
            "prolog",
            solidlsp_settings,
        )

    @classmethod
    @override
    def get_language_enum_instance(cls) -> Language:
        return Language.PROLOG

    @override
    def is_ignored_dirname(self, dirname: str) -> bool:
        return super().is_ignored_dirname(dirname) or dirname in (
            ".swipl",      # SWI-Prolog runtime cache
            "pack",        # SWI-Prolog pack installation directory
        )

    @staticmethod
    def _get_initialize_params(repository_absolute_path: str) -> InitializeParams:
        """Prolog initialize-params: quickfix + refactor.rename.

        The ``lsp_server`` pack supports ``textDocument/rename`` for Prolog
        variables and atoms.  We advertise ``quickfix`` for diagnostic fixes
        and ``refactor.rename`` because Prolog predicate renaming is a clean
        alpha-substitution — safe by design.

        No ``refactor.extract`` because goal extraction requires binding-context
        analysis that the current lsp_server pack does not implement.
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
                    "rename": {
                        "dynamicRegistration": True,
                        "prepareSupport": True,
                    },
                    "codeAction": {
                        "dynamicRegistration": True,
                        "codeActionLiteralSupport": {
                            "codeActionKind": {
                                "valueSet": [
                                    # Diagnostic quick-fixes: singleton variables,
                                    # syntax errors, unused predicates.
                                    "quickfix",
                                    # Predicate and variable renaming.
                                    # Prolog rename is a clean alpha-substitution
                                    # (symbolic names, no dependent types).
                                    "refactor.rename",
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
        """Boot swipl lsp_server: register handlers, start subprocess, initialize."""

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

        log.info("Starting swipl lsp_server process")
        self.server.start()
        initialize_params = self._get_initialize_params(self.repository_root_path)

        log.info("Sending initialize request to swipl lsp_server")
        init_response = self.server.send.initialize(initialize_params)
        log.debug("swipl lsp_server initialize response: %s", init_response)

        caps = init_response["capabilities"]
        assert "textDocumentSync" in caps, (
            "swipl lsp_server did not advertise textDocumentSync"
        )

        self.server.notify.initialized({})
        log.info("swipl lsp_server initialization complete")
