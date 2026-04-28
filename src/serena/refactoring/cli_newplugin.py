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
        # Stream 6 / Leaf F: SMT-LIB 2 constraint format.
        # No production LSP exists as of 2026-04-27; Smt2Installer raises
        # NotImplementedError with guidance.  The seam is preserved here.
        #
        # SMT-LIB 2 is a constraint specification format — rename/extract have
        # no solver-level semantics.  Only quickfix (diagnostic auto-corrections)
        # is safe to advertise.  See smt2_strategy.py for the full rationale.
        language="smt2",
        display_name="SMT-LIB 2",
        file_extensions=(".smt2", ".smt"),
        lsp_server_cmd=("smt2-lsp", "--stdio"),
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
