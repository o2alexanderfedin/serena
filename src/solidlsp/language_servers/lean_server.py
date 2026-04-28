"""Lean 4 LSP adapter — Stream 6 / Leaf E.

Mirrors the ``JdtlsServer`` shape: single-LSP-per-language, sync facade
methods, ``server_id: ClassVar[str] = "lean"``. The adapter spawns the
host's ``lean --server`` command (installed via ``elan``) over stdio.

Lean 4 (https://leanprover.github.io/lean4/) is a dependently-typed
theorem prover and programming language developed at Microsoft Research.
Its built-in language server (``lean --server``) is invoked directly over
stdio — there is no separate binary to install; the LSP server ships with
the ``lean`` compiler itself.

Lean 4 is a **theorem prover** — programs and proofs are the same thing.
This has a critical implication for the refactor surface: rename and
extract operations can **change the meaning of a theorem** (a renamed
hypothesis is a different hypothesis; extracting a subterm out of a proof
context can break definitional equality). The strategy-layer therefore
exposes only ``quickfix`` code actions (tactic suggestions such as
``"Try this: simp [...]"``), which are semantics-preserving hints offered
by the elaborator.

Binary entry point: ``lean`` (part of the Lean 4 toolchain)
Install via elan (https://github.com/leanprover/elan):
  ``curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh``
  then ``elan toolchain install stable``

Lean 4 code action kinds:

  ``quickfix``  — tactic suggestions and diagnostic quick-fixes.
                  Examples: "Try this: exact ⟨_, rfl⟩", "Try this: simp [...]".
                  These are semantics-preserving (they satisfy the goal;
                  the user can always reject them).

  No ``refactor.*`` kinds — renaming a Lean declaration can invalidate
  dependently-typed proofs elsewhere in the file or downstream. Safe
  structural refactors require a proof-aware rewriter that LSP code
  actions do not currently provide.
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


class LeanServer(SolidLanguageServer):
    """Lean 4 LSP adapter (host-binary; installed via LeanInstaller / elan).

    Targets a host-installed ``lean`` binary (managed via elan). The
    ``lean --server`` invocation starts the built-in LSP server over stdio;
    all that the adapter must do is spawn it and handle the Lean-specific
    notification set.

    Lean 4 is a theorem prover — its code action surface is limited to
    ``quickfix`` tactic suggestions (e.g. ``"Try this: simp [...]"``).
    Rename and extract operations are deliberately excluded because
    dependent types mean that renaming a hypothesis or extracting a
    subterm can silently invalidate proofs.  See module docstring for
    the full rationale.
    """

    server_id: ClassVar[str] = "lean"

    def __init__(
        self,
        config: LanguageServerConfig,
        repository_root_path: str,
        solidlsp_settings: SolidLSPSettings,
    ) -> None:
        # Host-binary discovery via PATH. LeanInstaller can populate PATH
        # (or ensure the binary exists) before the strategy spawns the adapter.
        binary = shutil.which("lean")
        if binary is None:
            log.debug(
                "lean binary not on PATH; spawn will fail until LeanInstaller runs"
            )
            binary = "lean"  # nominal — start_server will surface the failure
        super().__init__(
            config,
            repository_root_path,
            ProcessLaunchInfo(
                cmd=f"{binary} --server",
                cwd=repository_root_path,
            ),
            "lean4",
            solidlsp_settings,
        )

    @classmethod
    @override
    def get_language_enum_instance(cls) -> Language:
        return Language.LEAN4

    @override
    def is_ignored_dirname(self, dirname: str) -> bool:
        # Lean 4 projects accumulate large build artifacts in .lake/build;
        # skip them so the workspace-symbol crawl stays fast.
        return super().is_ignored_dirname(dirname) or dirname in (
            ".lake",    # Lake build cache and package store
            "build",    # Generic build output
            ".elan",    # elan toolchain cache (usually in HOME, but some projects put it here)
        )

    @staticmethod
    def _get_initialize_params(repository_absolute_path: str) -> InitializeParams:
        """Lean 4 initialize-params: quickfix code actions only.

        Lean 4's LSP supports textDocument/{definition,references,hover,
        documentSymbol,foldingRange,codeAction,completion}.  We advertise
        only the ``quickfix`` codeActionKind because rename/extract are
        not safe for theorem provers (see module docstring).
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
                                    # Tactic suggestions and diagnostic quick-fixes.
                                    # This is the ONLY kind Lean 4 exposes that is
                                    # safe for a theorem prover (see module docstring).
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
        """Boot lean --server: register handlers, start subprocess, initialize."""

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
        # Lean-specific notifications
        self.server.on_notification("$/lean/fileProgress", do_nothing)
        self.server.on_notification("$/lean/importClosure", do_nothing)

        log.info("Starting lean --server process")
        self.server.start()
        initialize_params = self._get_initialize_params(self.repository_root_path)

        log.info("Sending initialize request to lean --server")
        init_response = self.server.send.initialize(initialize_params)
        log.debug("lean --server initialize response: %s", init_response)

        # Sanity-check that critical capabilities are present.
        caps = init_response["capabilities"]
        assert "textDocumentSync" in caps, "lean --server did not advertise textDocumentSync"

        self.server.notify.initialized({})
        log.info("lean --server initialization complete")
