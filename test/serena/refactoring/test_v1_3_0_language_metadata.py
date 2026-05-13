"""Stage v1.3.0 generator metadata coverage for the 5 new languages.

Serena v1.3.0 added five languages to ``solidlsp.ls_config.Language``
(``ada``, ``angular``, ``bsl``, ``html``, ``scss``). The
``o2-scalpel-newplugin`` generator's per-language metadata table
(``serena.refactoring.cli_newplugin._LANGUAGE_METADATA``) MUST have a
row for each so ``make generate-plugins ada angular bsl html scss``
succeeds in the parent o2-scalpel repo.

This test pins the contract: missing rows make ``_resolve_strategy``
raise ``KeyError`` and the CLI exit with code 2.
"""

from __future__ import annotations

import pytest

from serena.refactoring.cli_newplugin import (
    _LANGUAGE_METADATA,
    _resolve_strategy,
)

V1_3_0_NEW_LANGUAGES: tuple[str, ...] = ("ada", "angular", "bsl", "html", "scss")


@pytest.mark.parametrize("lang", V1_3_0_NEW_LANGUAGES)
def test_new_v1_3_0_language_has_metadata(lang: str) -> None:
    """Every v1.3.0 newcomer must be present in ``_LANGUAGE_METADATA``."""

    assert lang in _LANGUAGE_METADATA, f"{lang} missing from _LANGUAGE_METADATA"


@pytest.mark.parametrize("lang", V1_3_0_NEW_LANGUAGES)
def test_new_v1_3_0_language_resolves(lang: str) -> None:
    """``_resolve_strategy`` must return a fully populated view for each."""

    sv = _resolve_strategy(lang)
    assert sv.language == lang
    assert sv.display_name, f"{lang}: display_name must be non-empty"
    assert sv.file_extensions, f"{lang}: file_extensions must be non-empty tuple"
    assert sv.lsp_server_cmd, f"{lang}: lsp_server_cmd must be non-empty tuple"
    # All extensions must start with a dot.
    for ext in sv.file_extensions:
        assert ext.startswith("."), f"{lang}: extension {ext!r} missing leading dot"
