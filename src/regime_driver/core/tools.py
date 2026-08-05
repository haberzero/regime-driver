"""Deterministic tools for TOOL nodes (pure domain logic).

A TOOL node runs a *fixed* tool (no model in the loop) against the current run
environment (context + report) and produces a ``ToolResult``. The result is
exposed to the run environment as ``ok`` / ``message`` so a following route or
gate node can branch deterministically on it.

Tools are pure functions: ``(context, report, args) -> ToolResult``. They never
perform arbitrary shell execution or network I/O; they only inspect the text
from the run. This keeps the kernel's tool surface safe and auditable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .models import Node


class UnknownToolError(Exception):
    """Raised when a TOOL node names a tool that is not registered."""


@dataclass
class ToolResult:
    """Result of running a deterministic tool."""

    ok: bool
    message: str
    data: dict = field(default_factory=dict)


# -- built-in tools ----------------------------------------------------------

def _noop(context: str, report: str, args: dict) -> ToolResult:
    """Always succeeds; useful for a placeholder / pass-through tool node."""
    return ToolResult(ok=True, message="noop")


def _have_report(context: str, report: str, args: dict) -> ToolResult:
    """Succeeds when the developer produced a non-empty report."""
    ok = bool(report and report.strip())
    return ToolResult(ok=ok, message="report present" if ok else "no report")


def _report_mentions(context: str, report: str, args: dict) -> ToolResult:
    """Succeeds when the report contains every word in args['words']."""
    words = _words_from_args(args)
    if not words:
        return ToolResult(ok=False, message="no words configured for report_mentions")
    missing = [w for w in words if w not in (report or "")]
    return ToolResult(
        ok=not missing,
        message="report mentions all words" if not missing else f"report missing: {', '.join(missing)}",
        data={"missing": missing},
    )


def _context_mentions(context: str, report: str, args: dict) -> ToolResult:
    """Succeeds when the task context contains every word in args['words']."""
    words = _words_from_args(args)
    if not words:
        return ToolResult(ok=False, message="no words configured for context_mentions")
    missing = [w for w in words if w not in (context or "")]
    return ToolResult(
        ok=not missing,
        message="context mentions all words" if not missing else f"context missing: {', '.join(missing)}",
        data={"missing": missing},
    )


def _words_from_args(args: dict) -> list:
    """Extract the word list from a tool's args (either `words` or a single `word`)."""
    words = args.get("words")
    if words is None and args.get("word") is not None:
        words = [args["word"]]
    return words or []


#: Registry of built-in deterministic tools (name -> callable).
TOOLS: dict[str, Callable[[str, str, dict], ToolResult]] = {
    "noop": _noop,
    "have_report": _have_report,
    "report_mentions": _report_mentions,
    "context_mentions": _context_mentions,
}


def register_tool(name: str, fn: Callable[[str, str, dict], ToolResult]) -> None:
    """Register a custom deterministic tool (user specialization)."""
    TOOLS[name] = fn


def run_tool(node: Node, context: str, report: str) -> ToolResult:
    """Run the tool named by a TOOL node against the run environment.

    Raises ``UnknownToolError`` if the node names an unregistered tool.
    """
    name = node.tool or ""
    fn = TOOLS.get(name)
    if fn is None:
        raise UnknownToolError(f"unknown tool '{name}' on node '{node.id}'")
    return fn(context or "", report or "", node.tool_args or {})