"""Stage 1G — 8 always-on primitive / safety / diagnostics MCP tools.

Each ``Scalpel*Tool`` subclass is auto-discovered by
``iter_subclasses(Tool)`` (``serena/mcp.py:249``); the snake-cased
class name (``Tool.get_name_from_cls``) becomes the MCP tool name.

Docstrings on every ``apply`` method are <=30 words (router signage,
§5.4): imperative verb + discriminator + contract bit.
"""

from __future__ import annotations

from typing import Literal

from serena.tools.scalpel_runtime import ScalpelRuntime
from serena.tools.scalpel_schemas import (
    CapabilityDescriptor,
    CapabilityFullDescriptor,
    ErrorCode,
    FailureInfo,
)
from serena.tools.tools_base import Tool


class ScalpelCapabilitiesListTool(Tool):
    """List capabilities for a language with optional filter."""

    def apply(
        self,
        language: Literal["rust", "python"] | None = None,
        filter_kind: str | None = None,
        applies_to_symbol_kind: str | None = None,
    ) -> str:
        """List capabilities for a language with optional filter. Returns
        capability_id + title + applies_to_kinds + preferred_facade.

        :param language: 'rust' or 'python'; None returns both languages.
        :param filter_kind: LSP code-action kind prefix to filter by.
        :param applies_to_symbol_kind: reserved (Stage 2A); unused at MVP.
        :return: JSON array of CapabilityDescriptor rows.
        """
        del applies_to_symbol_kind  # reserved for Stage 2A
        catalog = ScalpelRuntime.instance().catalog()
        rows: list[CapabilityDescriptor] = []
        for rec in catalog.records:
            if language is not None and rec.language != language:
                continue
            if filter_kind is not None and not rec.kind.startswith(filter_kind):
                continue
            rows.append(CapabilityDescriptor(
                capability_id=rec.id,
                title=rec.id.rsplit(".", 1)[-1].replace("_", " ").title(),
                language=rec.language,
                kind=rec.kind,
                source_server=rec.source_server,
                preferred_facade=rec.preferred_facade,
            ))
        return "[" + ",".join(r.model_dump_json() for r in rows) + "]"


class ScalpelCapabilityDescribeTool(Tool):
    """Describe one capability_id (full schema)."""

    def apply(self, capability_id: str) -> str:
        """Return full schema, examples, and pre-conditions for one
        capability_id. Call before invoking unknown capabilities.

        :param capability_id: stable o2.scalpel-issued id (e.g.
            'rust.refactor.extract.module'). Source: capabilities_list.
        :return: JSON CapabilityFullDescriptor or {failure: ...} payload.
        """
        catalog = ScalpelRuntime.instance().catalog()
        for rec in catalog.records:
            if rec.id == capability_id:
                desc = CapabilityFullDescriptor(
                    capability_id=rec.id,
                    title=rec.id.rsplit(".", 1)[-1].replace("_", " ").title(),
                    language=rec.language,
                    kind=rec.kind,
                    source_server=rec.source_server,
                    preferred_facade=rec.preferred_facade,
                    params_schema=rec.params_schema,
                    extension_allow_list=tuple(sorted(rec.extension_allow_list)),
                    description=(
                        f"{rec.kind} from {rec.source_server} (Stage 1F catalog)."
                    ),
                )
                return desc.model_dump_json(indent=2)
        # Unknown id — emit a structured failure payload that mirrors
        # FailureInfo so the LLM can read the same shape it sees on
        # apply_capability failures.
        candidates = sorted(
            r.id for r in catalog.records
            if any(part in r.id for part in capability_id.split("."))
        )[:5]
        failure = FailureInfo(
            stage="scalpel_capability_describe",
            symbol=capability_id,
            reason=f"Unknown capability_id: {capability_id!r}",
            code=ErrorCode.CAPABILITY_NOT_AVAILABLE,
            recoverable=True,
            candidates=tuple(candidates),
        )
        return '{"failure": ' + failure.model_dump_json() + "}"


__all__ = [
    "ScalpelCapabilitiesListTool",
    "ScalpelCapabilityDescribeTool",
]
