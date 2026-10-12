"""Domain-specific, bounded agent tools.

Every tool is a plain Python function taking a :class:`ToolContext` and
typed arguments, returning a bounded Pydantic result -- callable and
testable with no LLM involved. The agent (Phase 8) never gets
unrestricted filesystem, shell, or GitHub access: these tools are the
entire investigation surface.
"""
