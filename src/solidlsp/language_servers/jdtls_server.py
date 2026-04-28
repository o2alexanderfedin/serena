"""jdtls LSP adapter — Stream 6 / Leaf D.

Mirrors the ``ClangdServer`` shape: single-LSP-per-language, sync facade
methods, ``server_id: ClassVar[str] = "jdtls"``. The adapter spawns the
host's ``jdtls`` wrapper script (installed via ``brew install jdtls`` on
macOS or ``snap install jdtls --classic`` on Linux) over stdio.

jdtls (https://github.com/eclipse-jdtls/eclipse.jdt.ls) is the Eclipse JDT
Language Server — the canonical Java LSP maintained by the Eclipse Foundation.
It is the backend used by VSCode's Language Support for Java extension
(redhat-developer/vscode-java) and the richest Java LSP available.

Binary entry point: ``jdtls`` (a wrapper script that locates Java + the JAR).
Install (macOS): ``brew install jdtls``
Install (Linux): ``snap install jdtls --classic``

Unlike the legacy ``EclipseJDTLS`` class (which auto-downloads its own
bundled JRE + JDTLS JAR), this adapter targets a *host-installed* ``jdtls``
binary (managed via ``JdtlsInstaller`` / ``scalpel_install_lsp_servers``).
This keeps the adapter KISS-compliant and consistent with the S6 pattern.

jdtls code action kinds (sourced from
https://github.com/eclipse-jdtls/eclipse.jdt.ls and LSP cap introspection
of ``JdtlsServer._get_initialize_params``):

  ``source.organizeImports``           — remove unused imports and sort.
  ``source.generate.constructor``      — generate constructor(s).
  ``source.generate.hashCodeEquals``   — generate hashCode / equals pair.
  ``source.generate.toString``         — generate toString() override.
  ``source.generate.accessors``        — generate getters and setters.
  ``source.generate.overrideMethods``  — generate override stubs.
  ``source.generate.delegateMethods``  — generate delegate method stubs.
  ``refactor.extract.method``          — extract selection to a new method.
  ``refactor.extract.variable``        — extract expression to a local variable.
  ``refactor.extract.field``           — extract expression to a field.
  ``refactor.extract.interface``       — extract interface from class.
  ``refactor.inline``                  — inline a local variable or method.
  ``refactor.rewrite``                 — rewrite (convert, invert, etc.).
  ``quickfix``                         — quick-fix offered diagnostics.
  ``refactor``                         — root parent kind (server may use for grouping).
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


class JdtlsServer(SolidLanguageServer):
    """jdtls LSP adapter (host-binary; installed via JdtlsInstaller).

    Targets a host-installed ``jdtls`` wrapper script (not the auto-downloading
    legacy ``EclipseJDTLS`` adapter). The wrapper script locates the Java
    runtime and the JDTLS launcher JAR automatically; all that the adapter
    must do is spawn it over stdio.

    jdtls is the richest Java LSP available — it supports the full refactor
    surface: extract method/variable/field/interface, inline, rewrite,
    generate (constructors, hashCode/equals, toString, accessors, overrides),
    organize imports, and quick-fixes.
    """

    server_id: ClassVar[str] = "jdtls"

    def __init__(
        self,
        config: LanguageServerConfig,
        repository_root_path: str,
        solidlsp_settings: SolidLSPSettings,
    ) -> None:
        # Host-binary discovery via PATH. JdtlsInstaller can populate PATH
        # (or ensure the binary exists) before the strategy spawns the adapter.
        binary = shutil.which("jdtls")
        if binary is None:
            log.debug(
                "jdtls binary not on PATH; spawn will fail until JdtlsInstaller runs"
            )
            binary = "jdtls"  # nominal — start_server will surface the failure
        super().__init__(
            config,
            repository_root_path,
            ProcessLaunchInfo(
                cmd=binary,
                cwd=repository_root_path,
            ),
            "java",
            solidlsp_settings,
        )

    @classmethod
    @override
    def get_language_enum_instance(cls) -> Language:
        return Language.JAVA

    @override
    def is_ignored_dirname(self, dirname: str) -> bool:
        # Java projects routinely contain large build directories from Maven,
        # Gradle, and Eclipse; skip them so the workspace-symbol crawl stays fast.
        return super().is_ignored_dirname(dirname) or dirname in (
            "target",       # Maven
            "build",        # Gradle
            ".gradle",      # Gradle cache
            "bin",          # Eclipse compiled output
            "out",          # IntelliJ IDEA
            "classes",      # Generic compiled output
            "dist",         # Distribution artifacts
            "lib",          # Vendored JARs
            "node_modules", # Hybrid projects
            ".cache",
        )

    @staticmethod
    def _get_initialize_params(repository_absolute_path: str) -> InitializeParams:
        """jdtls initialize-params: full refactor + import organisation + generate advertised."""
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
                                    # import management
                                    "source.organizeImports",
                                    # code generation
                                    "source.generate.constructor",
                                    "source.generate.hashCodeEquals",
                                    "source.generate.toString",
                                    "source.generate.accessors",
                                    "source.generate.overrideMethods",
                                    "source.generate.delegateMethods",
                                    # extract refactors
                                    "refactor.extract",
                                    "refactor.extract.method",
                                    "refactor.extract.variable",
                                    "refactor.extract.field",
                                    "refactor.extract.interface",
                                    # inline refactors
                                    "refactor.inline",
                                    # rewrite refactors
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
                    "implementation": {"dynamicRegistration": True, "linkSupport": True},
                    "typeDefinition": {"dynamicRegistration": True, "linkSupport": True},
                    "callHierarchy": {"dynamicRegistration": True},
                    "typeHierarchy": {"dynamicRegistration": True},
                },
            },
            "workspaceFolders": [
                {"uri": root_uri, "name": pathlib.Path(repository_absolute_path).name}
            ],
        }
        return cast(InitializeParams, params)

    def _start_server(self) -> None:
        """Boot jdtls: register handlers, start subprocess, initialize."""

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
        self.server.on_notification("language/status", do_nothing)
        self.server.on_notification("language/actionableNotification", do_nothing)

        log.info("Starting jdtls server process")
        self.server.start()
        initialize_params = self._get_initialize_params(self.repository_root_path)

        log.info("Sending initialize request to jdtls")
        init_response = self.server.send.initialize(initialize_params)
        log.debug("jdtls initialize response: %s", init_response)

        # Sanity-check that critical capabilities are present.
        caps = init_response["capabilities"]
        assert "textDocumentSync" in caps, "jdtls did not advertise textDocumentSync"

        self.server.notify.initialized({})
        log.info("jdtls initialization complete")
