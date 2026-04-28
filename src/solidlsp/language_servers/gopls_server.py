"""gopls LSP adapter — Stream 6 / Leaf B.

Mirrors the ``VtslsServer`` shape: single-LSP-per-language, sync facade
methods, ``server_id: ClassVar[str] = "gopls"``. The adapter spawns the
host's ``gopls`` binary (installed via ``go install
golang.org/x/tools/gopls@latest``) over stdio using the ``gopls serve``
subcommand.

gopls (https://github.com/golang/tools/tree/master/gopls) is the official
Go language server maintained by the Go team. It implements the full LSP
subset relevant for code actions / rename / references.

Binary entry point: ``gopls serve`` (or bare ``gopls`` — both work; the
``serve`` subcommand is the recommended LSP invocation).
Install: ``go install golang.org/x/tools/gopls@latest``

The existing ``Gopls`` class at ``gopls.py`` is the *legacy* adapter
(auto-installs; used by ``Language.GO.get_ls_class()``). This adapter is
separate because:

  - It targets the o2-scalpel strategy/capability stack and declares
    ``server_id`` so the dynamic-capability registry can track it.
  - It expects a *host-installed* binary (via ``GoplsInstaller`` /
    ``scalpel_install_lsp_servers``) rather than auto-downloading at boot.
  - It advertises full Go refactor code-action kinds so the catalog
    introspection (Stage 1F) can derive the capability rows statically.

gopls code action kinds (sourced from gopls documentation + LSP cap
introspection of ``GoplsServer._get_initialize_params``):

  ``source.organizeImports`` — remove unused imports, sort import order.
  ``source.fixAll``          — apply all auto-fixable diagnostics at once.
  ``refactor.extract``       — generic extract refactor family.
  ``refactor.extract.function``  — extract selection into a new function.
  ``refactor.extract.variable``  — extract expression into a new variable.
  ``refactor.inline``        — inline a function at all call sites.
  ``refactor.rewrite``       — rewrite (e.g. fill struct, fill switch).
  ``quickfix``               — quick-fix offered diagnostics.
  ``refactor``               — root parent kind (server may use for grouping).
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


class GoplsServer(SolidLanguageServer):
    """gopls LSP adapter (host-binary; installed via GoplsInstaller)."""

    server_id: ClassVar[str] = "gopls"

    def __init__(
        self,
        config: LanguageServerConfig,
        repository_root_path: str,
        solidlsp_settings: SolidLSPSettings,
    ) -> None:
        # Host-binary discovery via PATH. GoplsInstaller can populate PATH
        # (or ensure the binary exists) before the strategy spawns the adapter.
        binary = shutil.which("gopls")
        if binary is None:
            log.debug(
                "gopls binary not on PATH; spawn will fail until GoplsInstaller runs"
            )
            binary = "gopls"  # nominal — start_server will surface the failure
        super().__init__(
            config,
            repository_root_path,
            ProcessLaunchInfo(
                cmd=f"{binary} serve",
                cwd=repository_root_path,
            ),
            "go",
            solidlsp_settings,
        )

    @classmethod
    @override
    def get_language_enum_instance(cls) -> Language:
        return Language.GO

    @override
    def is_ignored_dirname(self, dirname: str) -> bool:
        # Go projects routinely contain large vendored directories; skip them
        # so the workspace-symbol crawl stays fast and accurate.
        return super().is_ignored_dirname(dirname) or dirname in (
            "vendor",
            "dist",
            "build",
            "node_modules",
            ".cache",
            "testdata",
        )

    @staticmethod
    def _get_initialize_params(repository_absolute_path: str) -> InitializeParams:
        """gopls initialize-params: full refactor + import organisation advertised."""
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
                    "executeCommand": {"dynamicRegistration": True},
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
                        "completionItem": {"snippetSupport": True},
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
                    "rename": {
                        "dynamicRegistration": True,
                        "prepareSupport": True,
                    },
                    "codeAction": {
                        "dynamicRegistration": True,
                        "codeActionLiteralSupport": {
                            "codeActionKind": {
                                "valueSet": [
                                    # source-level actions
                                    "source.organizeImports",
                                    "source.fixAll",
                                    # extract / inline refactors
                                    "refactor.extract",
                                    "refactor.extract.function",
                                    "refactor.extract.variable",
                                    "refactor.inline",
                                    "refactor.rewrite",
                                    # quickfix
                                    "quickfix",
                                    # generic refactor
                                    "refactor",
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
        """Boot gopls: register handlers, start subprocess, initialize."""

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

        log.info("Starting gopls server process")
        self.server.start()
        initialize_params = self._get_initialize_params(self.repository_root_path)

        log.info("Sending initialize request to gopls")
        init_response = self.server.send.initialize(initialize_params)
        log.debug("gopls initialize response: %s", init_response)

        # Sanity-check that critical capabilities are present.
        caps = init_response["capabilities"]
        assert "textDocumentSync" in caps, "gopls did not advertise textDocumentSync"

        self.server.notify.initialized({})
        log.info("gopls initialization complete")
