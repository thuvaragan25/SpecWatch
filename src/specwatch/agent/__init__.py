"""The Investigator Agent: a bounded, tool-calling loop over the
deterministic indexes and verifiers built in earlier phases.

Everything in ``agent.tools`` is plain, independently-testable Python --
no LangGraph or LLM dependency. Only ``agent.graph`` (Phase 8) wires them
into an LLM-callable loop.
"""
