"""vtsls LSP adapter — Stream 6 / Leaf A.

Mirrors the ``MarksmanLanguageServer`` shape: single-LSP-per-language, sync
facade methods, ``server_id: ClassVar[str] = "vtsls"``. The adapter spawns
the host's ``vtsls`` binary (from a global npm install of
``@vtsls/language-server``) over stdio with the ``--stdio`` flag.

The legacy ``VtsLanguageServer`` (at ``vts_language_server.py``) carries a
100-LoC npm-download-on-first-use dependency provider and is wired to the
experimental ``Language.TYPESCRIPT_VTS`` enum value. This adapter is separate
because:

  - It targets ``Language.TYPESCRIPT`` (the non-experimental value) and
    declares ``server_id`` so the dynamic-capability registry can track it.
  - It expects a *host-installed* binary (via ``VtslsInstaller`` /
    ``scalpel_install_lsp_servers``) rather than auto-downloading at boot time.
  - It advertises full TS refactor code-action kinds so the catalog
    introspection (Stage 1F) can derive the capability rows statically.

vtsls (https://github.com/yioneko/vtsls) wraps VSCode's TypeScript extension
bundled language server. It implements the standard LSP subset relevant for
code actions / rename / references.

Binary entry point: ``vtsls --stdio``
npm install: ``npm install -g @vtsls/language-server``
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


class VtslsServer(SolidLanguageServer):
    """vtsls LSP adapter (host-binary; installed via VtslsInstaller)."""

    server_id: ClassVar[str] = "vtsls"

    def __init__(
        self,
        config: LanguageServerConfig,
        repository_root_path: str,
        solidlsp_settings: SolidLSPSettings,
    ) -> None:
        # Host-binary discovery via PATH. VtslsInstaller can populate PATH
        # (or ensure the binary exists) before the strategy spawns the adapter.
        binary = shutil.which("vtsls")
        if binary is None:
            log.debug(
                "vtsls binary not on PATH; spawn will fail until VtslsInstaller runs"
            )
            binary = "vtsls"  # nominal — start_server will surface the failure
        super().__init__(
            config,
            repository_root_path,
            ProcessLaunchInfo(
                cmd=f"{binary} --stdio",
                cwd=repository_root_path,
            ),
            "typescript",
            solidlsp_settings,
        )

    @classmethod
    @override
    def get_language_enum_instance(cls) -> Language:
        return Language.TYPESCRIPT

    @override
    def is_ignored_dirname(self, dirname: str) -> bool:
        # TS projects routinely contain large generated directories; skip them
        # so the workspace-symbol crawl stays fast and accurate.
        return super().is_ignored_dirname(dirname) or dirname in (
            "node_modules",
            "dist",
            "build",
            "out",
            ".next",
            ".nuxt",
            "coverage",
            ".cache",
        )

    @staticmethod
    def _get_initialize_params(repository_absolute_path: str) -> InitializeParams:
        """vtsls initialize-params: full refactor + import organisation advertised."""
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
                                    "refactor.extract.type",
                                    "refactor.extract.constant",
                                    "refactor.inline",
                                    "refactor.inline.variable",
                                    "refactor.move",
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
            "initializationOptions": {
                # Tell vtsls to use the bundled tsserver rather than requiring a
                # per-project node_modules/typescript install.
                "typescript": {
                    "tsserver": {
                        "useSyntaxServer": "auto",
                    },
                },
            },
        }
        return cast(InitializeParams, params)

    def _start_server(self) -> None:
        """Boot vtsls: register handlers, start subprocess, initialize."""

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

        log.info("Starting vtsls server process")
        self.server.start()
        initialize_params = self._get_initialize_params(self.repository_root_path)

        log.info("Sending initialize request to vtsls")
        init_response = self.server.send.initialize(initialize_params)
        log.debug("vtsls initialize response: %s", init_response)

        # Sanity-check that critical capabilities are present.
        caps = init_response["capabilities"]
        assert "textDocumentSync" in caps, "vtsls did not advertise textDocumentSync"

        self.server.notify.initialized({})
        log.info("vtsls initialization complete")
