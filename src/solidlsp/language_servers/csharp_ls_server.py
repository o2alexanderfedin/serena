"""csharp-ls LSP adapter — Stream 6 / Leaf I.

Mirrors the ``JdtlsServer`` shape: single-LSP-per-language, sync facade
methods, ``server_id: ClassVar[str] = "csharp-ls"``. The adapter spawns the
host's ``csharp-ls`` binary (installed via ``dotnet tool install --global
csharp-ls``) over stdio.

csharp-ls (https://github.com/razzmatazz/csharp-language-server) is a
Roslyn-based C# LSP server that wraps the .NET compiler platform for
refactoring operations. It is simpler to install than OmniSharp (no
tarball + Mono dance) — a single dotnet-tool invocation puts the binary on
PATH.

Binary entry point: ``csharp-ls``
Install: ``dotnet tool install --global csharp-ls``

csharp-ls code action kinds (sourced from
https://github.com/razzmatazz/csharp-language-server and LSP cap
introspection of ``CsharpLsServer._get_initialize_params``):

  ``quickfix``                        — quick-fix offered diagnostics.
  ``source.organizeImports``          — remove unused usings and sort.
  ``refactor.extract.method``         — extract selection to a new method.
  ``refactor.extract.variable``       — extract expression to a local variable.
  ``refactor.inline.method``          — inline a method at all call sites.
  ``refactor.rewrite``                — rewrite (convert, invert, etc.).
  ``refactor``                        — root parent kind (server may use for grouping).
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


class CsharpLsServer(SolidLanguageServer):
    """csharp-ls LSP adapter (host-binary; installed via CsharpLsInstaller).

    Targets a host-installed ``csharp-ls`` binary (managed via
    ``CsharpLsInstaller`` / ``scalpel_install_lsp_servers``). The binary
    is a self-contained dotnet global tool; all that the adapter must do is
    spawn it over stdio.

    csharp-ls is Roslyn-based and supports the full refactor surface for C#:
    quick-fixes, organize usings, extract method/variable, inline method, and
    rewrite transformations.
    """

    server_id: ClassVar[str] = "csharp-ls"

    def __init__(
        self,
        config: LanguageServerConfig,
        repository_root_path: str,
        solidlsp_settings: SolidLSPSettings,
    ) -> None:
        # Host-binary discovery via PATH. CsharpLsInstaller can populate PATH
        # (or ensure the binary exists) before the strategy spawns the adapter.
        binary = shutil.which("csharp-ls")
        if binary is None:
            log.debug(
                "csharp-ls binary not on PATH; spawn will fail until CsharpLsInstaller runs"
            )
            binary = "csharp-ls"  # nominal — start_server will surface the failure
        super().__init__(
            config,
            repository_root_path,
            ProcessLaunchInfo(
                cmd=binary,
                cwd=repository_root_path,
            ),
            "csharp",
            solidlsp_settings,
        )

    @classmethod
    @override
    def get_language_enum_instance(cls) -> Language:
        return Language.CSHARP

    @override
    def is_ignored_dirname(self, dirname: str) -> bool:
        # C# / .NET projects accumulate large build artifacts; skip them so
        # the workspace-symbol crawl stays fast.
        return super().is_ignored_dirname(dirname) or dirname in (
            "bin",          # compiled output
            "obj",          # intermediate build artifacts
            "packages",     # NuGet package cache (older projects)
            ".vs",          # Visual Studio local state
            ".nuget",       # NuGet cache
            "TestResults",  # VS test output
            "artifacts",    # SDK-style build artifacts directory
        )

    @staticmethod
    def _get_initialize_params(repository_absolute_path: str) -> InitializeParams:
        """csharp-ls initialize-params: full refactor + import organisation advertised.

        csharp-ls supports textDocument/{definition,references,hover,
        documentSymbol,codeAction,rename,completion,foldingRange,formatting}.
        Code actions include quickfix, source.organizeImports, refactor.extract.*,
        refactor.inline.method, and refactor.rewrite.*.
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
                        "willSave": True,
                        "willSaveWaitUntil": True,
                        "didSave": True,
                    },
                    "completion": {
                        "dynamicRegistration": True,
                        "completionItem": {"snippetSupport": False},
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
                                    # quick-fix offered diagnostics
                                    "quickfix",
                                    # import management
                                    "source.organizeImports",
                                    # extract refactors
                                    "refactor.extract",
                                    "refactor.extract.method",
                                    "refactor.extract.variable",
                                    # inline refactors
                                    "refactor.inline",
                                    "refactor.inline.method",
                                    # rewrite refactors
                                    "refactor.rewrite",
                                    # generic refactor
                                    "refactor",
                                ],
                            },
                        },
                        "resolveSupport": {"properties": ["edit"]},
                    },
                    "foldingRange": {"dynamicRegistration": True},
                    "formatting": {"dynamicRegistration": True},
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
        """Boot csharp-ls: register handlers, start subprocess, initialize."""

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

        log.info("Starting csharp-ls server process")
        self.server.start()
        initialize_params = self._get_initialize_params(self.repository_root_path)

        log.info("Sending initialize request to csharp-ls")
        init_response = self.server.send.initialize(initialize_params)
        log.debug("csharp-ls initialize response: %s", init_response)

        # Sanity-check that critical capabilities are present.
        caps = init_response["capabilities"]
        assert "textDocumentSync" in caps, "csharp-ls did not advertise textDocumentSync"

        self.server.notify.initialized({})
        log.info("csharp-ls initialization complete")
