"""ProbLog LSP adapter — Stream 6 / Leaf H.

ProbLog (https://problog.readthedocs.io/) is a probabilistic logic programming
language developed at KU Leuven.  It extends Prolog with probabilistic facts
and rules, enabling reasoning about uncertainty.

**LSP ecosystem status (as of 2026-04-27) — research-mode:**

No production LSP server exists for ProbLog.  ProbLog is a research-mode
language primarily used in academic papers, probabilistic inference engines,
and DeepProbLog (neural-symbolic AI).  The language shares Prolog's grammar
substrate — ``.problog`` files are syntactically valid SWI-Prolog files
augmented with ``::``-prefixed probabilistic facts.

**Design decision — inherit Prolog's grammar, stub the binary:**

ProbLog files can be parsed and linted by a Prolog LSP server in a degraded
but useful mode:
  - Syntax errors and singleton-variable warnings are reported correctly.
  - Go-to-definition works for pure Prolog predicates.
  - Probabilistic annotations (``0.3 :: rain.``) may be flagged as unknown
    syntax by strict Prolog parsers but are typically tolerated.

This adapter therefore reuses the Prolog LSP launch command (``swipl`` +
``lsp_server`` pack) as its binary.  If a dedicated ProbLog LSP ships in the
future, only the binary / launch command here needs updating.

**Capability surface:**

``quickfix`` only — ProbLog's probabilistic semantics make rename/extract
operations research-mode:
  - Renaming a probabilistic fact identifier requires updating probability
    annotations and any EM-learning weights, which a Prolog LSP server cannot
    track.
  - Extracting a probabilistic subgoal changes the independence assumptions
    in the distribution, altering the semantics of the model.

These hazards are qualitatively different from standard Prolog rename and are
documented here per DRY rule so that the strategy allow-list reflects the
real semantics.

Binary entry point: ``swipl`` (shared with Prolog strategy).
Extensions: ``.problog``
Install: ``pip install problog`` (the Python inference engine; LSP piggybacks
on ``swipl`` + ``lsp_server`` pack — see ``PrologInstaller``).
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

# SWI-Prolog binary — ProbLog files share the Prolog grammar substrate and
# are parsed by the same swipl + lsp_server pack in degraded mode.
_SWIPL_BINARY = "swipl"

# Identical launch args to PrologServer — the lsp_server pack is unaware of
# the distinction between plain Prolog and ProbLog files.
_SWIPL_LSP_ARGS = (
    "-g", "use_module(library(lsp_server)).",
    "-g", "lsp_server:main",
    "-t", "halt",
    "--", "stdio",
)


class ProblogServer(SolidLanguageServer):
    """ProbLog LSP adapter (research-mode; inherits Prolog grammar via swipl).

    No dedicated ProbLog LSP exists.  This adapter piggybacks on the
    SWI-Prolog ``lsp_server`` pack (same binary/args as ``PrologServer``),
    providing syntax-level diagnostics and go-to-definition for the pure
    Prolog subset.  Probabilistic annotations are tolerated but not
    semantics-aware.

    Capability surface: ``quickfix`` only — rename/extract are excluded
    because ProbLog's probabilistic semantics make them research-mode
    (see module docstring for the full rationale).

    Install the inference engine:
      ``pip install problog``
    Install the LSP backend (shared with Prolog):
      ``swipl -g "pack_install(lsp_server)" -t halt``
    """

    server_id: ClassVar[str] = "problog-lsp"

    def __init__(
        self,
        config: LanguageServerConfig,
        repository_root_path: str,
        solidlsp_settings: SolidLSPSettings,
    ) -> None:
        binary = shutil.which(_SWIPL_BINARY)
        if binary is None:
            log.debug(
                "swipl binary not on PATH; ProbLog LSP spawn will fail — "
                "install SWI-Prolog and the lsp_server pack (see ProblogInstaller)."
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
            "prolog",  # ProbLog shares Prolog's language-id for the swipl parser
            solidlsp_settings,
        )

    @classmethod
    @override
    def get_language_enum_instance(cls) -> Language:
        return Language.PROBLOG

    @override
    def is_ignored_dirname(self, dirname: str) -> bool:
        return super().is_ignored_dirname(dirname) or dirname in (
            ".swipl",    # SWI-Prolog runtime cache
            "__pycache__",  # Python inference engine cache (problog pip package)
        )

    @staticmethod
    def _get_initialize_params(repository_absolute_path: str) -> InitializeParams:
        """ProbLog initialize-params: quickfix code actions only.

        ProbLog's probabilistic semantics make rename/extract research-mode:
        renaming a probabilistic fact must also update its probability weight
        and any EM-learning callbacks; the current Prolog LSP backend cannot
        track these cross-cutting concerns.  ``quickfix`` is safe because it
        is limited to syntax-level fixes (singleton variables, parse errors).
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
                                    # Syntax-level diagnostic fixes only.
                                    # Rename / extract excluded — see module docstring
                                    # for the probabilistic-semantics rationale.
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
        """Boot swipl lsp_server for ProbLog: register handlers, initialize."""

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

        log.info("Starting swipl lsp_server process for ProbLog")
        self.server.start()
        initialize_params = self._get_initialize_params(self.repository_root_path)

        log.info("Sending initialize request to swipl lsp_server (ProbLog mode)")
        init_response = self.server.send.initialize(initialize_params)
        log.debug("swipl lsp_server (ProbLog) initialize response: %s", init_response)

        caps = init_response["capabilities"]
        assert "textDocumentSync" in caps, (
            "swipl lsp_server (ProbLog mode) did not advertise textDocumentSync"
        )

        self.server.notify.initialized({})
        log.info("swipl lsp_server (ProbLog mode) initialization complete")
