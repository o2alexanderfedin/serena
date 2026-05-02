"""Stage 1J ``o2-scalpel-newplugin`` CLI entry point.

Generates a Claude Code plugin tree at ``--out / o2-scalpel-<lang>/``
for the given ``--language``. The strategy resolver is split out as
:func:`_resolve_strategy` so tests can monkey-patch it without touching
the registry.

Stream 5 / Leaf 01 Task 4 added the opt-in ``--repo-root`` flag: when
supplied, the generator regenerates the parent ``marketplace.json`` after
the plugin tree write so the unified manifest stays in lockstep with the
trees it lists. Drift-CI gates the file, so any plugin emit that forgets
``--repo-root`` is caught at CI time.

v1.2 reconciliation collapsed the previous ``marketplace.surface.json``
(schema-driven, engine-internal) into the boostvolt-shape
``marketplace.json``: the refresh hook now writes a single file, sourced
from per-plugin ``plugin.json`` metadata.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from serena.refactoring.plugin_generator import PluginGenerator


@dataclass(frozen=True)
class _Facade:
    """Generator-shape facade entry."""

    name: str
    summary: str
    trigger_phrases: tuple[str, ...]
    primitive_chain: tuple[str, ...]


@dataclass(frozen=True)
class _StrategyView:
    """Adapter exposing the metadata the Stage 1J generator needs.

    The Stage 1E ``LanguageStrategy`` Protocol only carries the LSP wiring
    surface (``language_id``, ``extension_allow_list``, ``build_servers``);
    it does not yet expose display name, server command, or facade lists
    that the plugin generator templates consume. We bridge that gap with
    a per-language metadata table here. Stage 1H/1K may merge this back
    into the strategy Protocol once the FacadeRouter lands.
    """

    language: str
    display_name: str
    file_extensions: tuple[str, ...]
    lsp_server_cmd: tuple[str, ...]
    facades: tuple[_Facade, ...] = field(default_factory=tuple)


# Per-language metadata table. Add a row + verify the smoke goldens (T10)
# whenever a new ``LanguageStrategy`` is registered.
_LANGUAGE_METADATA: dict[str, _StrategyView] = {
    "rust": _StrategyView(
        language="rust",
        display_name="Rust",
        file_extensions=(".rs",),
        lsp_server_cmd=("rust-analyzer",),
        facades=(
            _Facade(
                name="split_file",
                summary="Split a file along symbol boundaries",
                trigger_phrases=("split this file", "extract symbols"),
                primitive_chain=(
                    "textDocument/codeAction",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
        ),
    ),
    "python": _StrategyView(
        language="python",
        display_name="Python",
        file_extensions=(".py", ".pyi"),
        lsp_server_cmd=("pylsp",),
        facades=(
            _Facade(
                name="split_file",
                summary="Split a Python module along symbol boundaries",
                trigger_phrases=("split module", "extract symbols"),
                primitive_chain=(
                    "textDocument/codeAction",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
        ),
    ),
    "markdown": _StrategyView(
        # v1.1.1 Leaf 01: marksman ``server`` subcommand drives the LSP over
        # stdio. The four facades below are the contract Leaf 02 will
        # implement (``ScalpelRenameHeadingTool``, ``ScalpelSplitDocTool``,
        # ``ScalpelExtractSectionTool``, ``ScalpelOrganizeLinksTool``); this
        # row only declares them so the plugin generator can render the
        # marketplace + skill trees ahead of facade-class wiring.
        language="markdown",
        display_name="Markdown",
        file_extensions=(".md", ".markdown", ".mdx"),
        lsp_server_cmd=("marksman", "server"),
        facades=(
            _Facade(
                name="rename_heading",
                summary="Rename a heading and update all cross-file wiki-links",
                trigger_phrases=("rename heading", "refactor heading"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="split_doc",
                summary="Split a long markdown doc along H1/H2 boundaries into linked sub-docs",
                trigger_phrases=("split this doc", "split markdown"),
                primitive_chain=(
                    "textDocument/documentSymbol",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="extract_section",
                summary="Extract a section into a new file with a back-link",
                trigger_phrases=("extract section", "extract heading"),
                primitive_chain=(
                    "textDocument/documentSymbol",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="organize_links",
                summary="Sort and normalize markdown links/wiki-links",
                trigger_phrases=("organize links", "sort links"),
                primitive_chain=(
                    "textDocument/documentLink",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "go": _StrategyView(
        # Stream 6 / Leaf B: gopls ``serve`` drives the LSP over stdio.
        # gopls is the official Go language server maintained by the Go team
        # (https://github.com/golang/tools/tree/master/gopls). Installed via
        # Go toolchain: ``go install golang.org/x/tools/gopls@latest``.
        language="go",
        display_name="Go",
        file_extensions=(".go",),
        lsp_server_cmd=("gopls", "serve"),
        facades=(
            _Facade(
                name="split_file",
                summary="Split a Go file along symbol boundaries",
                trigger_phrases=("split this file", "extract symbols"),
                primitive_chain=(
                    "textDocument/codeAction",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="extract",
                summary="Extract selection into a function or variable",
                trigger_phrases=("extract this", "extract function", "extract variable"),
                primitive_chain=(
                    "textDocument/codeAction[refactor.extract]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="inline",
                summary="Inline a function at all call sites",
                trigger_phrases=("inline this", "inline function"),
                primitive_chain=(
                    "textDocument/codeAction[refactor.inline]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="rename",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="organize_imports",
                summary="Remove unused imports and sort import order",
                trigger_phrases=("organize imports", "sort imports", "clean imports"),
                primitive_chain=(
                    "textDocument/codeAction[source.organizeImports]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply all auto-fixable diagnostics (source.fixAll)",
                trigger_phrases=("fix all", "fix lints", "auto fix"),
                primitive_chain=(
                    "textDocument/codeAction[source.fixAll]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "typescript": _StrategyView(
        # Stream 6 / Leaf A: vtsls ``--stdio`` drives the LSP over stdio.
        # vtsls wraps VSCode's TypeScript extension bundled language server
        # (https://github.com/yioneko/vtsls). Installed globally via npm:
        # ``npm install -g @vtsls/language-server``.
        language="typescript",
        display_name="TypeScript",
        file_extensions=(".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".mjs", ".cjs"),
        lsp_server_cmd=("vtsls", "--stdio"),
        facades=(
            _Facade(
                name="split_file",
                summary="Split a TypeScript/JavaScript file along symbol boundaries",
                trigger_phrases=("split this file", "extract symbols"),
                primitive_chain=(
                    "textDocument/codeAction",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="extract",
                summary="Extract selection into a function, variable, or constant",
                trigger_phrases=("extract this", "extract function", "extract variable"),
                primitive_chain=(
                    "textDocument/codeAction[refactor.extract]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="inline",
                summary="Inline a local variable or function at all call sites",
                trigger_phrases=("inline this", "inline variable"),
                primitive_chain=(
                    "textDocument/codeAction[refactor.inline]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="rename",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="organize_imports",
                summary="Remove unused imports and sort import order",
                trigger_phrases=("organize imports", "sort imports", "clean imports"),
                primitive_chain=(
                    "textDocument/codeAction[source.organizeImports]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply all auto-fixable diagnostics (source.fixAll)",
                trigger_phrases=("fix all", "fix lints", "auto fix"),
                primitive_chain=(
                    "textDocument/codeAction[source.fixAll]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "java": _StrategyView(
        # Stream 6 / Leaf D: jdtls (Eclipse JDT Language Server) drives the
        # LSP over stdio. jdtls is the canonical Java LSP maintained by the
        # Eclipse Foundation (https://github.com/eclipse-jdtls/eclipse.jdt.ls).
        # It is the backend used by VSCode's Language Support for Java extension
        # and the richest Java LSP available.
        # Install (macOS): ``brew install jdtls``
        # Install (Linux): ``snap install jdtls --classic``
        language="java",
        display_name="Java",
        file_extensions=(".java",),
        lsp_server_cmd=("jdtls",),
        facades=(
            _Facade(
                name="split_file",
                summary="Split a Java file along class/method boundaries",
                trigger_phrases=("split this file", "extract class"),
                primitive_chain=(
                    "textDocument/codeAction",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="extract",
                summary="Extract selection into a method or variable",
                trigger_phrases=("extract this", "extract method", "extract variable"),
                primitive_chain=(
                    "textDocument/codeAction[refactor.extract]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="inline",
                summary="Inline a local variable or method at all call sites",
                trigger_phrases=("inline this", "inline variable", "inline method"),
                primitive_chain=(
                    "textDocument/codeAction[refactor.inline]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="rename",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="organize_imports",
                summary="Remove unused imports and sort import order",
                trigger_phrases=("organize imports", "sort imports", "clean imports"),
                primitive_chain=(
                    "textDocument/codeAction[source.organizeImports]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="generate",
                summary="Generate constructors, getters/setters, hashCode/equals, or toString",
                trigger_phrases=("generate constructor", "generate getter", "generate setter", "generate equals"),
                primitive_chain=(
                    "textDocument/codeAction[source.generate]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply all auto-fixable diagnostics (quickfix)",
                trigger_phrases=("fix all", "fix lints", "auto fix"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "cpp": _StrategyView(
        # Stream 6 / Leaf C: clangd drives the LSP over stdio.
        # clangd is the canonical C/C++ language server from the LLVM project
        # (https://clangd.llvm.org). Installed via llvm formula on macOS
        # (``brew install llvm``) or snap on Linux
        # (``snap install clangd --classic``).
        # A single unified language_id="cpp" covers both C and C++ sources —
        # clangd auto-detects C vs. C++ mode from the file extension and
        # compile_commands.json database.
        language="cpp",
        display_name="C/C++",
        file_extensions=(
            ".c", ".cc", ".cpp", ".cxx", ".c++",
            ".h", ".hh", ".hpp", ".hxx", ".h++",
            ".ipp", ".inl", ".tpp",
        ),
        lsp_server_cmd=("clangd",),
        facades=(
            _Facade(
                name="split_file",
                summary="Split a C/C++ file along symbol boundaries",
                trigger_phrases=("split this file", "extract symbols"),
                primitive_chain=(
                    "textDocument/codeAction",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="extract",
                summary="Extract selection into a function",
                trigger_phrases=("extract this", "extract function"),
                primitive_chain=(
                    "textDocument/codeAction[refactor.extract]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="inline",
                summary="Inline a function at all call sites",
                trigger_phrases=("inline this", "inline function"),
                primitive_chain=(
                    "textDocument/codeAction[refactor.inline]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="rename",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="organize_includes",
                summary="Sort and deduplicate #include directives",
                trigger_phrases=("organize includes", "sort includes", "clean includes"),
                primitive_chain=(
                    "textDocument/codeAction[source.organizeImports]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply all auto-fixable diagnostics (source.fixAll.clangd)",
                trigger_phrases=("fix all", "fix lints", "auto fix"),
                primitive_chain=(
                    "textDocument/codeAction[source.fixAll.clangd]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "smt2": _StrategyView(
        # Stream 6 / Leaf F (v1.4.1): SMT-LIB 2 backed by `dolmenls` (Dolmen
        # monorepo, https://github.com/Gbury/dolmen). Diagnostics-focused LSP;
        # dolmenls speaks stdio with no required args, hence ``("dolmenls",)``.
        #
        # SMT-LIB 2 is a constraint specification format — rename/extract have
        # no solver-level semantics.  Only quickfix (diagnostic auto-corrections)
        # is safe to advertise.  See smt2_strategy.py for the full rationale.
        language="smt2",
        display_name="SMT-LIB 2",
        file_extensions=(".smt2", ".smt"),
        lsp_server_cmd=("dolmenls",),
        facades=(
            _Facade(
                name="fix_lints",
                summary="Apply diagnostic quick-fixes (sort mismatch, syntax errors)",
                trigger_phrases=("fix all", "fix lints", "fix syntax"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "prolog": _StrategyView(
        # Stream 6 / Leaf G: SWI-Prolog via lsp_server pack.
        # Install: swipl -g "pack_install(lsp_server)" -t halt
        # Requires SWI-Prolog 8.1.5+.
        #
        # Prolog predicates are purely symbolic names — alpha-renaming is safe.
        # quickfix covers diagnostic fixes; refactor.rename covers predicate
        # and variable renaming within the current file.
        language="prolog",
        display_name="Prolog (SWI-Prolog)",
        file_extensions=(".pl", ".pro", ".prolog"),
        lsp_server_cmd=(
            "swipl",
            "-g", "use_module(library(lsp_server)).",
            "-g", "lsp_server:main",
            "-t", "halt",
            "--", "stdio",
        ),
        facades=(
            _Facade(
                name="fix_lints",
                summary="Apply diagnostic quick-fixes (singleton variables, syntax errors)",
                trigger_phrases=("fix all", "fix lints", "fix singleton"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="rename_predicate",
                summary="Rename a Prolog predicate or variable across the current file",
                trigger_phrases=("rename", "rename predicate", "rename variable"),
                primitive_chain=(
                    "textDocument/rename",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "problog": _StrategyView(
        # Stream 6 / Leaf H: ProbLog (probabilistic Prolog) — research-mode.
        # No dedicated LSP; piggybacks on swipl + lsp_server pack.
        # Install: pip install problog + swipl lsp_server pack.
        #
        # Probabilistic semantics make rename/extract research-mode:
        # renaming a probabilistic fact must also update EM-learning weights.
        # Only quickfix (syntax-level fixes) is safe.
        language="problog",
        display_name="ProbLog",
        file_extensions=(".problog",),
        lsp_server_cmd=(
            "swipl",
            "-g", "use_module(library(lsp_server)).",
            "-g", "lsp_server:main",
            "-t", "halt",
            "--", "stdio",
        ),
        facades=(
            _Facade(
                name="fix_lints",
                summary="Apply diagnostic quick-fixes (singleton variables, syntax errors)",
                trigger_phrases=("fix all", "fix lints", "fix syntax"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "lean": _StrategyView(
        # Stream 6 / Leaf E: ``lean --server`` drives the LSP over stdio.
        # Lean 4 (https://leanprover.github.io/lean4/) is a dependently-typed
        # theorem prover. Its LSP server is built into the ``lean`` compiler
        # binary — no separate binary download is required.
        #
        # Install via elan (the Lean toolchain manager):
        #   curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh
        #   elan toolchain install stable
        #
        # Only ``quickfix`` code actions are exposed because dependent types
        # make rename/extract semantically unsafe — renaming a hypothesis
        # or extracting a subterm can silently invalidate proofs elsewhere.
        # See lean_strategy.py module docstring for the full rationale.
        language="lean",
        display_name="Lean 4",
        file_extensions=(".lean",),
        lsp_server_cmd=("lean", "--server"),
        facades=(
            _Facade(
                name="fix_lints",
                summary="Apply tactic suggestions and auto-fixable diagnostics (quickfix)",
                trigger_phrases=("fix all", "fix lints", "apply tactic", "try this"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "haxe": _StrategyView(
        # v1.9.8: haxe-language-server (https://github.com/vshaxe/haxe-language-server)
        # is the canonical Haxe LSP, distributed as a Node.js bundle. The host binary
        # ``haxe`` provides the compiler; the language server runs as
        # ``node /path/to/haxe-language-server/bin/server.js`` — the SolidLSP adapter
        # discovers the entry script via npm/VSCode-extension search, so the surface
        # cmd here is the user-visible ``haxe-language-server`` shim.
        # Install: ``npm install -g haxe-language-server`` (requires haxe + nekovm).
        # Capability surface: rename + extract + fix_lints (rich Haxe LSP).
        language="haxe",
        display_name="Haxe",
        file_extensions=(".hx",),
        lsp_server_cmd=("haxe-language-server",),
        facades=(
            _Facade(
                name="rename",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="extract",
                summary="Extract selection into a function or variable",
                trigger_phrases=("extract this", "extract function", "extract variable"),
                primitive_chain=(
                    "textDocument/codeAction[refactor.extract]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="organize_imports",
                summary="Remove unused imports and sort import order",
                trigger_phrases=("organize imports", "sort imports", "clean imports"),
                primitive_chain=(
                    "textDocument/codeAction[source.organizeImports]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply all auto-fixable diagnostics (quickfix)",
                trigger_phrases=("fix all", "fix lints", "auto fix"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "erlang": _StrategyView(
        # v1.9.8: erlang_ls (https://github.com/erlang-ls/erlang_ls) is the canonical
        # Erlang LSP. Installed via ``brew install erlang_ls`` on macOS or built from
        # source on Linux. Speaks stdio with explicit ``--transport stdio`` flag —
        # the adapter wraps the binary the same way.
        # Capability surface: rename + extract + fix_lints (full Erlang LSP).
        language="erlang",
        display_name="Erlang",
        file_extensions=(".erl", ".hrl", ".escript"),
        lsp_server_cmd=("erlang_ls", "--transport", "stdio"),
        facades=(
            _Facade(
                name="rename",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="extract",
                summary="Extract selection into a function or variable",
                trigger_phrases=("extract this", "extract function", "extract variable"),
                primitive_chain=(
                    "textDocument/codeAction[refactor.extract]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply all auto-fixable diagnostics (quickfix)",
                trigger_phrases=("fix all", "fix lints", "auto fix"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "ocaml": _StrategyView(
        # v1.9.8: ocaml-lsp-server (https://github.com/ocaml/ocaml-lsp). The
        # canonical OCaml LSP, installed via opam: ``opam install ocaml-lsp-server``.
        # The SolidLSP adapter wraps via ``opam exec -- ocamllsp`` so opam env is
        # respected; the surface ``lsp_server_cmd`` is the binary name.
        # Capability surface: rename + extract + fix_lints (full OCaml LSP).
        language="ocaml",
        display_name="OCaml",
        file_extensions=(".ml", ".mli", ".re", ".rei"),
        lsp_server_cmd=("ocamllsp",),
        facades=(
            _Facade(
                name="rename",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="extract",
                summary="Extract selection into a let-binding or function",
                trigger_phrases=("extract this", "extract function", "extract let"),
                primitive_chain=(
                    "textDocument/codeAction[refactor.extract]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply all auto-fixable diagnostics (quickfix)",
                trigger_phrases=("fix all", "fix lints", "auto fix"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "powershell": _StrategyView(
        # v1.9.8: PowerShell Editor Services (https://github.com/PowerShell/PowerShellEditorServices).
        # The canonical PowerShell LSP, hosted inside ``pwsh`` and launched with the
        # ``-Stdio`` flag (the adapter wires the full ``pwsh -Command`` invocation).
        # Install: ``Install-Module -Name PowerShellEditorServices`` from a pwsh prompt.
        # Capability surface: rename + fix_lints (PSES rename is solid; extract is
        # weaker than other LSPs, so kept off the headline surface).
        language="powershell",
        display_name="PowerShell",
        file_extensions=(".ps1", ".psm1", ".psd1"),
        lsp_server_cmd=("pwsh",),
        facades=(
            _Facade(
                name="rename",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply all auto-fixable diagnostics (quickfix)",
                trigger_phrases=("fix all", "fix lints", "auto fix"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "systemverilog": _StrategyView(
        # v1.9.8: verible-verilog-ls (https://github.com/chipsalliance/verible).
        # Verible's SystemVerilog LSP is diagnostics-focused: rename and extract
        # are not implemented (HDL semantics make rename across module hierarchies
        # research-mode). Only quickfix-style diagnostic auto-corrections + format
        # are exposed.
        # Install: ``brew install verible`` on macOS, prebuilt binaries on GH Releases.
        language="systemverilog",
        display_name="SystemVerilog",
        file_extensions=(".sv", ".svh", ".v", ".vh"),
        lsp_server_cmd=("verible-verilog-ls",),
        facades=(
            _Facade(
                name="fix_lints",
                summary="Apply diagnostic quick-fixes (lint warnings, syntax issues)",
                trigger_phrases=("fix all", "fix lints", "auto fix"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "clojure": _StrategyView(
        # v1.9.8: clojure-lsp (https://github.com/clojure-lsp/clojure-lsp).
        # Mature LSP for Clojure / ClojureScript / EDN; supports rename, extract,
        # and a rich set of refactor.* code actions (move-to-let, cycle-coll, etc.).
        # Install: ``brew install clojure-lsp/brew/clojure-lsp-native`` on macOS
        # or download the standalone binary from GH Releases.
        # Capability surface: rename + extract + fix_lints.
        language="clojure",
        display_name="Clojure",
        file_extensions=(".clj", ".cljs", ".cljc", ".edn"),
        lsp_server_cmd=("clojure-lsp",),
        facades=(
            _Facade(
                name="rename",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="extract",
                summary="Extract selection into a function or let-binding",
                trigger_phrases=("extract this", "extract function", "extract let"),
                primitive_chain=(
                    "textDocument/codeAction[refactor.extract]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply clj-kondo + clojure-lsp diagnostic quick-fixes",
                trigger_phrases=("fix all", "fix lints", "auto fix"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "crystal": _StrategyView(
        # v1.9.8: crystalline (https://github.com/elbywan/crystalline). The active
        # Crystal LSP. Install: ``brew install crystalline`` on macOS or build from
        # source via ``shards build``. Crystal is statically typed with a
        # Ruby-flavored surface; the LSP supports rename + diagnostic quickfix.
        # Extract remains research-mode upstream so it's omitted from the headline.
        language="crystal",
        display_name="Crystal",
        file_extensions=(".cr",),
        lsp_server_cmd=("crystalline",),
        facades=(
            _Facade(
                name="rename",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply Crystal compiler + ameba diagnostic quick-fixes",
                trigger_phrases=("fix all", "fix lints", "auto fix"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "elixir": _StrategyView(
        # v1.9.8: ElixirLS (https://github.com/elixir-lsp/elixir-ls). The canonical
        # Elixir LSP, installed via ``brew install elixir-ls`` on macOS. Speaks
        # stdio via the ``elixir-ls`` shim. ElixirLS supports rename + extract +
        # quickfix (credo + dialyzer warnings).
        language="elixir",
        display_name="Elixir",
        file_extensions=(".ex", ".exs"),
        lsp_server_cmd=("elixir-ls",),
        facades=(
            _Facade(
                name="rename",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="extract",
                summary="Extract selection into a function or variable",
                trigger_phrases=("extract this", "extract function", "extract variable"),
                primitive_chain=(
                    "textDocument/codeAction[refactor.extract]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply credo + dialyzer diagnostic quick-fixes",
                trigger_phrases=("fix all", "fix lints", "auto fix"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "haskell": _StrategyView(
        # v1.9.8: haskell-language-server (https://github.com/haskell/haskell-language-server).
        # Canonical Haskell LSP; install via ``ghcup install hls --set``. The wrapper
        # binary ``haskell-language-server-wrapper`` handles GHC version resolution
        # and forwards stdio to the matching ``haskell-language-server-<ghc>`` worker.
        # Capability surface: rename + extract + fix_lints (HLS retrie + hlint).
        language="haskell",
        display_name="Haskell",
        file_extensions=(".hs", ".lhs"),
        lsp_server_cmd=("haskell-language-server-wrapper", "--lsp"),
        facades=(
            _Facade(
                name="rename",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="extract",
                summary="Extract selection into a let-binding or function",
                trigger_phrases=("extract this", "extract function", "extract let"),
                primitive_chain=(
                    "textDocument/codeAction[refactor.extract]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply hlint + retrie diagnostic quick-fixes",
                trigger_phrases=("fix all", "fix lints", "auto fix"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "perl": _StrategyView(
        # v1.9.8: Perl::LanguageServer (https://github.com/richterger/Perl-LanguageServer).
        # Installed via cpanm: ``cpanm Perl::LanguageServer``. Speaks stdio. Perl's
        # dynamic dispatch makes whole-workspace rename research-mode upstream, so
        # the headline surface is rename (current file) + fix_lints. Extract is
        # not exposed.
        language="perl",
        display_name="Perl",
        file_extensions=(".pl", ".pm", ".t"),
        lsp_server_cmd=("perl", "-MPerl::LanguageServer", "-e", "Perl::LanguageServer::run"),
        facades=(
            _Facade(
                name="rename",
                summary="Rename a symbol within the current file",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply diagnostic quick-fixes (perlcritic, syntax)",
                trigger_phrases=("fix all", "fix lints", "auto fix"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "ruby": _StrategyView(
        # v1.9.8: ruby-lsp (https://github.com/Shopify/ruby-lsp). The modern,
        # actively maintained Ruby LSP from Shopify. Install via per-user gem:
        # ``gem install --user-install ruby-lsp`` and add the user gem bindir to
        # PATH. Supports rename + extract + fix_lints (rubocop + standard).
        language="ruby",
        display_name="Ruby",
        file_extensions=(".rb", ".erb"),
        lsp_server_cmd=("ruby-lsp",),
        facades=(
            _Facade(
                name="rename",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="extract",
                summary="Extract selection into a method or variable",
                trigger_phrases=("extract this", "extract method", "extract variable"),
                primitive_chain=(
                    "textDocument/codeAction[refactor.extract]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply rubocop + standard diagnostic quick-fixes",
                trigger_phrases=("fix all", "fix lints", "auto fix"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "csharp": _StrategyView(
        # Stream 6 / Leaf I: csharp-ls drives the LSP over stdio.
        # csharp-ls (https://github.com/razzmatazz/csharp-language-server) is a
        # Roslyn-based C# language server that is simpler to install than OmniSharp
        # (no tarball + Mono dance). It is distributed as a .NET global tool.
        # Install: ``dotnet tool install --global csharp-ls``
        # Ensure ~/.dotnet/tools is on PATH after install.
        # See csharp_strategy.py module docstring for the full rationale.
        language="csharp",
        display_name="C#",
        file_extensions=(".cs", ".csx"),
        lsp_server_cmd=("csharp-ls",),
        facades=(
            _Facade(
                name="extract",
                summary="Extract selection into a method or variable",
                trigger_phrases=("extract this", "extract method", "extract variable"),
                primitive_chain=(
                    "textDocument/codeAction[refactor.extract]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="inline",
                summary="Inline a method at all call sites",
                trigger_phrases=("inline this", "inline method"),
                primitive_chain=(
                    "textDocument/codeAction[refactor.inline]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="rename",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="organize_imports",
                summary="Remove unused using directives and sort import order",
                trigger_phrases=("organize imports", "sort imports", "clean imports", "organize usings"),
                primitive_chain=(
                    "textDocument/codeAction[source.organizeImports]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="rewrite",
                summary="Apply rewrite transformations (convert, invert, etc.)",
                trigger_phrases=("rewrite this", "convert to", "invert condition"),
                primitive_chain=(
                    "textDocument/codeAction[refactor.rewrite]",
                    "workspace/applyEdit",
                ),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply all auto-fixable diagnostics (quickfix)",
                trigger_phrases=("fix all", "fix lints", "auto fix"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    # v1.14: minimal-row generator coverage for the 29 engine-only primary
    # languages. Each row uses the universal ``rename_symbol`` + ``fix_lints``
    # facade pair — works with any LSP that supports ``textDocument/rename``
    # plus diagnostic-driven ``codeAction``. Adapter modules live under
    # ``solidlsp/language_servers/<lang>_*.py``; canonical file extensions
    # come from ``solidlsp.ls_config.Language._matcher``.
    "al": _StrategyView(
        # Microsoft Dynamics 365 Business Central / NAV scripting language.
        # The AL Language Server ships inside the ms-dynamics-smb.al VS Code
        # extension; the ALLanguageServer adapter auto-downloads the .vsix.
        language="al",
        display_name="AL",
        file_extensions=(".al", ".dal"),
        lsp_server_cmd=("al-language-server",),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "ansible": _StrategyView(
        # @ansible/ansible-language-server. Experimental in solidlsp because
        # it reuses YAML extensions; must be explicitly selected.
        language="ansible",
        display_name="Ansible",
        file_extensions=(".yaml", ".yml"),
        lsp_server_cmd=("ansible-language-server",),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "bash": _StrategyView(
        # bash-language-server (npm package by mads-hartmann).
        language="bash",
        display_name="Bash",
        file_extensions=(".sh", ".bash"),
        lsp_server_cmd=("bash-language-server", "start"),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "dart": _StrategyView(
        # Dart SDK ships ``dart language-server`` (analysis_server in stdio
        # mode). Single-binary install with the SDK from dart.dev.
        language="dart",
        display_name="Dart",
        file_extensions=(".dart",),
        lsp_server_cmd=("dart", "language-server"),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "elm": _StrategyView(
        # @elm-tooling/elm-language-server. Requires elm + elm-test on PATH
        # for full functionality.
        language="elm",
        display_name="Elm",
        file_extensions=(".elm",),
        lsp_server_cmd=("elm-language-server",),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "fortran": _StrategyView(
        # fortls (https://github.com/fortran-lang/fortls). pip-installable.
        language="fortran",
        display_name="Fortran",
        file_extensions=(".f90", ".F90", ".f95", ".F95", ".f03", ".F03", ".f08", ".F08", ".f", ".F", ".for", ".FOR", ".fpp", ".FPP"),
        lsp_server_cmd=("fortls",),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "fsharp": _StrategyView(
        # fsautocomplete (https://github.com/fsharp/FsAutoComplete). Installed
        # as a dotnet global tool.
        language="fsharp",
        display_name="F#",
        file_extensions=(".fs", ".fsx", ".fsi"),
        lsp_server_cmd=("fsautocomplete",),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "groovy": _StrategyView(
        # groovy-language-server (GroovyLanguageServer/groovy-language-server)
        # — distributed as a runnable jar. No package-manager install path.
        language="groovy",
        display_name="Groovy",
        file_extensions=(".groovy", ".gvy"),
        lsp_server_cmd=("groovy-language-server",),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "hlsl": _StrategyView(
        # antaalt/shader-language-server (also known as shader-sense). The
        # adapter auto-downloads the binary.
        language="hlsl",
        display_name="HLSL",
        file_extensions=(".hlsl", ".hlsli", ".fx", ".fxh", ".cginc", ".compute", ".shader", ".glsl", ".vert", ".frag", ".geom", ".tesc", ".tese", ".comp", ".wgsl"),
        lsp_server_cmd=("shader-language-server",),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "json": _StrategyView(
        # vscode-langservers-extracted ships ``vscode-json-languageserver``.
        language="json",
        display_name="JSON",
        file_extensions=(".json", ".jsonc"),
        lsp_server_cmd=("vscode-json-languageserver", "--stdio"),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "julia": _StrategyView(
        # julia-vscode/LanguageServer.jl. Conventionally invoked via
        # ``julia --project=@languageserver -e 'using LanguageServer; runserver()'``.
        # We list ``julia`` as the binary; the install hint documents the full
        # invocation.
        language="julia",
        display_name="Julia",
        file_extensions=(".jl",),
        lsp_server_cmd=("julia",),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "kotlin": _StrategyView(
        # fwcd/kotlin-language-server. Installed via release tarball; binary
        # named ``kotlin-language-server``.
        language="kotlin",
        display_name="Kotlin",
        file_extensions=(".kt", ".kts"),
        lsp_server_cmd=("kotlin-language-server",),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "lua": _StrategyView(
        # LuaLS/lua-language-server (sumneko-style).
        language="lua",
        display_name="Lua",
        file_extensions=(".lua",),
        lsp_server_cmd=("lua-language-server",),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "luau": _StrategyView(
        # JohnnyMorganz/luau-lsp — for Roblox's typed Luau dialect.
        language="luau",
        display_name="Luau",
        file_extensions=(".luau",),
        lsp_server_cmd=("luau-lsp", "lsp"),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "matlab": _StrategyView(
        # Official MathWorks matlab-language-server. Requires MATLAB R2021b+
        # and a Node.js runtime. Conventionally launched via the
        # ``matlab-language-server`` shim from the matlab-language-server
        # npm package.
        language="matlab",
        display_name="MATLAB",
        file_extensions=(".m", ".mlx", ".mlapp"),
        lsp_server_cmd=("matlab-language-server", "--stdio"),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "msl": _StrategyView(
        # Custom pygls server bundled with solidlsp for mIRC scripting (.mrc).
        # The MSLLanguageServer adapter manages a private virtualenv on first
        # use.
        language="msl",
        display_name="MSL",
        file_extensions=(".mrc",),
        lsp_server_cmd=("msl-lsp",),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "nix": _StrategyView(
        # nix-community/nixd — modern Nix LSP.
        language="nix",
        display_name="Nix",
        file_extensions=(".nix",),
        lsp_server_cmd=("nixd",),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "pascal": _StrategyView(
        # genericptr/pascal-language-server (pasls) — Free Pascal + Lazarus.
        language="pascal",
        display_name="Pascal",
        file_extensions=(".pas", ".pp", ".lpr", ".dpr", ".dpk", ".inc"),
        lsp_server_cmd=("pasls",),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "php": _StrategyView(
        # Intelephense (default in solidlsp). Closed-source freemium; the
        # ``php_phpactor`` alternate adapter ships the open-source path.
        language="php",
        display_name="PHP",
        file_extensions=(".php",),
        lsp_server_cmd=("intelephense", "--stdio"),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "r": _StrategyView(
        # REditorSupport/languageserver. Conventionally launched via
        # ``R --slave -e 'languageserver::run()'``.
        language="r",
        display_name="R",
        file_extensions=(".R", ".r", ".Rmd", ".Rnw"),
        lsp_server_cmd=("R", "--slave", "-e", "languageserver::run()"),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "rego": _StrategyView(
        # StyraInc/regal — modern Rego linter + LSP for OPA policies.
        language="rego",
        display_name="Rego",
        file_extensions=(".rego",),
        lsp_server_cmd=("regal", "language-server"),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "scala": _StrategyView(
        # scalameta/metals.
        language="scala",
        display_name="Scala",
        file_extensions=(".scala", ".sbt"),
        lsp_server_cmd=("metals",),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "solidity": _StrategyView(
        # @nomicfoundation/solidity-language-server.
        language="solidity",
        display_name="Solidity",
        file_extensions=(".sol",),
        lsp_server_cmd=("nomicfoundation-solidity-language-server", "--stdio"),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "swift": _StrategyView(
        # Swift toolchain ships sourcekit-lsp.
        language="swift",
        display_name="Swift",
        file_extensions=(".swift",),
        lsp_server_cmd=("sourcekit-lsp",),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "terraform": _StrategyView(
        # HashiCorp's terraform-ls.
        language="terraform",
        display_name="Terraform",
        file_extensions=(".tf", ".tfvars", ".tfstate"),
        lsp_server_cmd=("terraform-ls", "serve"),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "toml": _StrategyView(
        # tamasfe/taplo — TOML toolchain that doubles as an LSP via
        # ``taplo lsp stdio``.
        language="toml",
        display_name="TOML",
        file_extensions=(".toml",),
        lsp_server_cmd=("taplo", "lsp", "stdio"),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "vue": _StrategyView(
        # @vue/language-server (Volar).
        language="vue",
        display_name="Vue",
        file_extensions=(".vue",),
        lsp_server_cmd=("vue-language-server", "--stdio"),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "yaml": _StrategyView(
        # redhat-developer/yaml-language-server.
        language="yaml",
        display_name="YAML",
        file_extensions=(".yaml", ".yml"),
        lsp_server_cmd=("yaml-language-server", "--stdio"),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
    "zig": _StrategyView(
        # zigtools/zls.
        language="zig",
        display_name="Zig",
        file_extensions=(".zig", ".zon"),
        lsp_server_cmd=("zls",),
        facades=(
            _Facade(
                name="rename_symbol",
                summary="Rename a symbol across the workspace",
                trigger_phrases=("rename this", "refactor name"),
                primitive_chain=("textDocument/rename",),
            ),
            _Facade(
                name="fix_lints",
                summary="Apply LSP diagnostic quick-fixes",
                trigger_phrases=("fix lints", "apply quickfixes"),
                primitive_chain=(
                    "textDocument/codeAction[quickfix]",
                    "workspace/applyEdit",
                ),
            ),
        ),
    ),
}


def _resolve_strategy(language: str) -> Any:
    """Resolve the generator-shape view for ``language``.

    Returns a :class:`_StrategyView` (not the raw ``LanguageStrategy`` class)
    because the Stage 1E Protocol does not yet carry display name / server
    command / facade list. Raises :class:`KeyError` if the language is
    unknown.
    """

    if language not in _LANGUAGE_METADATA:
        raise KeyError(language)
    return _LANGUAGE_METADATA[language]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="o2-scalpel-newplugin",
        description="Generate an o2-scalpel-<lang>/ Claude Code plugin tree.",
    )
    p.add_argument(
        "--language",
        required=True,
        help="Target language (e.g. rust, python).",
    )
    p.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output parent directory.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing plugin tree at the target path.",
    )
    p.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help=(
            "Parent o2-scalpel repo root. When supplied, marketplace.json "
            "is regenerated under this directory in the same run as the "
            "plugin tree write. Drift-CI requires the regenerated "
            "marketplace.json to land in the same commit as the plugin-tree "
            "change — otherwise the gate fails."
        ),
    )
    return p


def _refresh_marketplace_surface(repo_root: Path) -> None:
    """Regenerate ``<repo_root>/marketplace.json`` from plugin trees.

    Imports the marketplace builder lazily so a ``serena.refactoring`` import
    doesn't pull the marketplace package eagerly (cheap layering hygiene).

    Function name preserved for backward call-site compatibility; the file
    written is now the unified ``marketplace.json`` (v1.2 reconciliation
    collapsed the previous parallel ``marketplace.surface.json``).
    """

    from serena.marketplace.build import (
        build_manifest,
        resolve_engine_sha,
        write_manifest,
    )

    manifest = build_manifest(repo_root, generator_sha=resolve_engine_sha())
    write_manifest(repo_root, manifest)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        strategy = _resolve_strategy(args.language)
    except KeyError:
        print(f"error: unknown language {args.language!r}", file=sys.stderr)
        return 2
    try:
        root = PluginGenerator().emit(strategy, args.out, force=args.force)
    except FileExistsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    if args.repo_root is not None:
        _refresh_marketplace_surface(args.repo_root)
    print(f"wrote {root}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
