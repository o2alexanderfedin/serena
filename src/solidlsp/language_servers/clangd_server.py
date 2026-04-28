"""clangd LSP adapter — Stream 6 / Leaf C.

Mirrors the ``GoplsServer`` shape: single-LSP-per-language, sync facade
methods, ``server_id: ClassVar[str] = "clangd"``. The adapter spawns the
host's ``clangd`` binary (installed via ``brew install llvm`` on macOS or
``snap install clangd`` on Linux) over stdio.

clangd (https://clangd.llvm.org) is the canonical C/C++ language server
maintained by the LLVM project. It implements the full LSP subset relevant
for code actions / rename / references, and adds LLVM-specific extensions
for include management, semantic tokens, and tweak-based refactors.

Binary entry point: ``clangd`` (bare invocation; clangd auto-detects stdio
mode when stdin is not a terminal).
Install (macOS): ``brew install llvm`` or ``brew install clangd``
Install (Linux): ``snap install clangd``

The unified language_id ``"cpp"`` covers both C and C++ because clangd
processes both via the same driver: it reads the compile-command database
(``compile_commands.json``) and determines C vs. C++ mode from file
extension and compile flags, not from a separate LSP configuration.

clangd code action kinds (sourced from https://clangd.llvm.org/extensions
and LSP cap introspection of ``ClangdServer._get_initialize_params``):

  ``source.organizeImports``    — sort / deduplicate #include directives.
  ``source.fixAll.clangd``      — apply all auto-fixable diagnostics.
  ``refactor.extract``          — generic extract refactor family.
  ``refactor.extract.function`` — extract selection into a new function.
  ``refactor.inline``           — inline a function at all call sites.
  ``quickfix``                  — quick-fix offered diagnostics.
  ``refactor``                  — root parent kind (server may use for grouping).
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


class ClangdServer(SolidLanguageServer):
    """clangd LSP adapter (host-binary; installed via ClangdInstaller).

    Handles both C and C++ files — clangd uses a single language server
    for all C-family languages. The language_id passed to the LSP protocol
    must be ``"cpp"`` for C++ files and ``"c"`` for pure C files; clangd
    accepts both. The o2.scalpel strategy layer uses a unified ``"cpp"``
    identifier and relies on clangd's compile-command database to resolve
    per-file C vs. C++ mode.
    """

    server_id: ClassVar[str] = "clangd"

    def __init__(
        self,
        config: LanguageServerConfig,
        repository_root_path: str,
        solidlsp_settings: SolidLSPSettings,
    ) -> None:
        # Host-binary discovery via PATH. ClangdInstaller can populate PATH
        # (or ensure the binary exists) before the strategy spawns the adapter.
        binary = shutil.which("clangd")
        if binary is None:
            log.debug(
                "clangd binary not on PATH; spawn will fail until ClangdInstaller runs"
            )
            binary = "clangd"  # nominal — start_server will surface the failure
        super().__init__(
            config,
            repository_root_path,
            ProcessLaunchInfo(
                cmd=binary,
                cwd=repository_root_path,
            ),
            "cpp",
            solidlsp_settings,
        )

    @classmethod
    @override
    def get_language_enum_instance(cls) -> Language:
        return Language.CPP

    @override
    def is_ignored_dirname(self, dirname: str) -> bool:
        # C/C++ projects routinely contain large build directories and third-party
        # vendored headers; skip them so the workspace-symbol crawl stays fast.
        return super().is_ignored_dirname(dirname) or dirname in (
            "build",
            "cmake-build-debug",
            "cmake-build-release",
            ".cmake",
            "CMakeFiles",
            "third_party",
            "third-party",
            "vendor",
            "node_modules",
            ".cache",
            "out",
        )

    @staticmethod
    def _get_initialize_params(repository_absolute_path: str) -> InitializeParams:
        """clangd initialize-params: full refactor + include organisation advertised."""
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
                                    # include / header management
                                    "source.organizeImports",
                                    # auto-fix all diagnostics
                                    "source.fixAll.clangd",
                                    # extract refactors
                                    "refactor.extract",
                                    "refactor.extract.function",
                                    # inline refactors
                                    "refactor.inline",
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
        """Boot clangd: register handlers, start subprocess, initialize."""

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

        log.info("Starting clangd server process")
        self.server.start()
        initialize_params = self._get_initialize_params(self.repository_root_path)

        log.info("Sending initialize request to clangd")
        init_response = self.server.send.initialize(initialize_params)
        log.debug("clangd initialize response: %s", init_response)

        # Sanity-check that critical capabilities are present.
        caps = init_response["capabilities"]
        assert "textDocumentSync" in caps, "clangd did not advertise textDocumentSync"

        self.server.notify.initialized({})
        log.info("clangd initialization complete")
