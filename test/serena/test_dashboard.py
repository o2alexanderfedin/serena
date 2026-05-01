from pathlib import Path
from types import SimpleNamespace

from serena.constants import SERENA_DASHBOARD_DIR
from serena.dashboard import SerenaDashboardAPI
from solidlsp.ls_config import Language


class _DummyMemoryLogHandler:
    def get_log_messages(self, from_idx: int = 0):  # pragma: no cover - simple stub
        return SimpleNamespace(messages=[], max_idx=-1)

    def clear_log_messages(self) -> None:  # pragma: no cover - simple stub
        pass


class _DummyAgent:
    def __init__(self, project: SimpleNamespace | None) -> None:
        self._project = project

    def execute_task(self, func, *, logged: bool | None = None, name: str | None = None):
        del logged, name
        return func()

    def get_active_project(self):
        return self._project


def _make_dashboard(project_languages: list[Language] | None) -> SerenaDashboardAPI:
    project = None
    if project_languages is not None:
        project = SimpleNamespace(project_config=SimpleNamespace(languages=project_languages))
    agent = _DummyAgent(project)
    return SerenaDashboardAPI(
        memory_log_handler=_DummyMemoryLogHandler(),  # pyright: ignore[reportArgumentType]
        tool_names=[],
        agent=agent,  # pyright: ignore[reportArgumentType]
        tool_usage_stats=None,
    )


def test_available_languages_include_experimental_when_no_active_project():
    dashboard = _make_dashboard(project_languages=None)
    response = dashboard._get_available_languages()
    expected = sorted(lang.value for lang in Language.iter_all(include_experimental=True))
    assert response.languages == expected


def test_available_languages_exclude_project_languages():
    dashboard = _make_dashboard(project_languages=[Language.PYTHON, Language.MARKDOWN])
    response = dashboard._get_available_languages()
    available = set(response.languages)
    assert Language.PYTHON.value not in available
    assert Language.MARKDOWN.value not in available
    # ensure experimental languages remain available for selection
    assert Language.ANSIBLE.value in available


def test_dashboard_html_carries_serena_attribution_and_differences() -> None:
    """The dashboard surfaces a fork-of-Serena attribution and a brief
    differences callout — required so end-users can trace the upstream
    project and understand what O2 Scalpel adds on top.

    See `docs/superpowers/specs/2026-04-29-...` family for the rebrand
    decision; the v1.8 dashboard rebrand intentionally keeps an upstream
    credit visible.
    """
    html = (Path(SERENA_DASHBOARD_DIR) / "index.html").read_text(encoding="utf-8")
    # Attribution
    assert "Serena" in html, "dashboard must reference upstream Serena project"
    assert "github.com/oraios/serena" in html, "dashboard must link to upstream Serena repo"
    assert "fork" in html.lower(), "dashboard must state O2 Scalpel is a fork"
    # Differences callout — at least one Scalpel-specific axis must be named
    differences_signals = ("LSP", "MCP", "facade", "refactor")
    assert any(signal in html for signal in differences_signals), (
        f"dashboard must name at least one Scalpel-specific addition "
        f"(any of {differences_signals})"
    )
    # Plugin language list: each of the 23 first-class plugin languages must appear.
    plugin_languages = (
        "clojure", "cpp", "crystal", "csharp", "elixir", "erlang", "go",
        "haskell", "haxe", "java", "lean", "markdown", "ocaml", "perl",
        "powershell", "problog", "prolog", "python", "ruby", "rust",
        "smt2", "systemverilog", "typescript",
    )
    missing = [lang for lang in plugin_languages if lang not in html]
    assert not missing, f"dashboard must list all 23 plugin languages — missing: {missing}"
    # Engine-only LSP coverage callout.
    assert "52 LSPs" in html or "engine level" in html, (
        "dashboard must mention the broader engine-level LSP coverage beyond the 23 plugins"
    )
