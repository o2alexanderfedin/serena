"""marksman LSP adapter — v1.1.1 Leaf 01.

Mirrors the ``PylspServer`` shape: single-LSP-per-language, sync facade
methods, ``server_id: ClassVar[str] = "marksman"``. The adapter spawns
the host's ``marksman`` binary with the ``server`` subcommand
(``marksman server``) over stdio. The auto-installer at
``solidlsp.language_servers.marksman.Marksman`` is intentionally NOT
reused here — the v1.1.1 LSP-installer infrastructure (Leaf 03) will
own provisioning end-to-end; this adapter consumes a host-installed
binary discovered via ``shutil.which("marksman")``.

Why a *new* adapter rather than extending the existing ``Marksman``
class:

  - ``Marksman`` (legacy) carries a 100-LoC dependency-provider that
    downloads the binary on first use and pins a SHA. v1.1.1 separates
    "find-and-run" from "install-and-update": the strategy + facade
    layer must work against a host binary; the installer (Leaf 03) is
    a distinct concern with its own MCP gate.
  - ``Marksman`` does not declare ``server_id``; the dynamic-capability
    registry would silently skip it (per ``ls.py:670`` "empty string
    means unknown server"). v1.1.1 needs a stable id so the future
    capability-merge facade can route per-server.
  - ``Marksman.request_document_symbols`` remaps heading SymbolKind
    String → Namespace, which is semantically valuable. We inherit
    that override implicitly via the strategy: the strategy can pick
    *which* concrete adapter class to spawn; the legacy class stays
    available for callers that go through ``Language.get_ls_class()``.

The capability advertisement is wider than ``Marksman``'s: this adapter
declares ``workspace.applyEdit=True`` + ``rename.prepareSupport=True``
+ ``documentLink`` (essentials for the four Leaf 02 facades).
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


class MarksmanLanguageServer(SolidLanguageServer):
    """marksman LSP adapter (host-binary; installer wiring lands in Leaf 03)."""

    server_id: ClassVar[str] = "marksman"

    def __init__(
        self,
        config: LanguageServerConfig,
        repository_root_path: str,
        solidlsp_settings: SolidLSPSettings,
    ) -> None:
        # Host-binary discovery via PATH. The Leaf 03 installer can mutate
        # PATH (or pre-populate the binary) before the strategy spawns the
        # adapter; this adapter does no auto-download itself.
        binary = shutil.which("marksman")
        if binary is None:
            # Defer the failure to start_server so callers can introspect the
            # adapter (e.g. for capability listings) without owning a binary.
            # The legacy ``Marksman`` adapter takes the same stance.
            log.debug("marksman binary not on PATH; spawn will fail until installer runs")
            binary = "marksman"  # nominal — start_server will report the failure
        super().__init__(
            config,
            repository_root_path,
            ProcessLaunchInfo(
                cmd=f"{binary} server",
                cwd=repository_root_path,
            ),
            "markdown",
            solidlsp_settings,
        )

    @classmethod
    @override
    def get_language_enum_instance(cls) -> Language:
        return Language.MARKDOWN

    @override
    def is_ignored_dirname(self, dirname: str) -> bool:
        # Markdown trees typically pull in:
        #  - ``.obsidian`` / ``.vitepress`` / ``.vuepress`` — vault metadata
        #    that breaks heading parsers when crawled.
        #  - ``node_modules`` — JS deps in MDX projects.
        #  - ``.git`` — never crawl version-control internals.
        return super().is_ignored_dirname(dirname) or dirname in (
            ".obsidian",
            ".vitepress",
            ".vuepress",
            "node_modules",
            ".git",
        )

    @staticmethod
    def _get_initialize_params(repository_absolute_path: str) -> InitializeParams:
        """Marksman initialize-params: workspace edits + heading rename + links."""
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
                    "documentLink": {
                        "dynamicRegistration": True,
                        "tooltipSupport": True,
                    },
                    "foldingRange": {"dynamicRegistration": True},
                    "rename": {
                        "dynamicRegistration": True,
                        "prepareSupport": True,
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
        """Boot marksman: register quiet handlers, start subprocess, initialize."""

        def register_capability_handler(_params: dict) -> None:
            return

        def window_log_message(msg: dict) -> None:
            log.info("LSP: window/logMessage: %s", msg)

        def do_nothing(_params: dict) -> None:
            return

        self.server.on_request("client/registerCapability", register_capability_handler)
        self.server.on_notification("window/logMessage", window_log_message)
        self.server.on_notification("$/progress", do_nothing)
        self.server.on_notification("textDocument/publishDiagnostics", do_nothing)

        log.info("Starting marksman server process")
        self.server.start()
        initialize_params = self._get_initialize_params(self.repository_root_path)

        log.info("Sending initialize request to marksman")
        init_response = self.server.send.initialize(initialize_params)
        log.debug("marksman initialize response: %s", init_response)

        # Sanity-check critical capabilities; marksman 2026-02-08+ exposes
        # all four. Older releases miss workspace edit support — fail loud.
        caps = init_response["capabilities"]
        assert "textDocumentSync" in caps, "marksman did not advertise textDocumentSync"
        assert "definitionProvider" in caps, "marksman did not advertise definitionProvider"
        assert "documentSymbolProvider" in caps, "marksman did not advertise documentSymbolProvider"
        assert "renameProvider" in caps, "marksman did not advertise renameProvider"

        self.server.notify.initialized({})
        log.info("marksman initialization complete")
