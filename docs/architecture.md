# SpecWatch Architecture

This document describes SpecWatch's own architectural constraints, used
to dogfood SpecWatch against its own repository (plan.md's Dogfooding
Requirement).

## Deterministic vs Agentic Boundary

The model must have agency over investigation but must not have agency
over truth. Every finding must pass the deterministic verifier before it
can be published; the verifier must not itself be another LLM call.

## Investigator Access Architecture

The Investigator must not have unrestricted filesystem, shell, or GitHub
mutation access. It may only call the narrow, bounded tools explicitly
exposed to it through the agent tool registry.

## Provider Independence Architecture

The rest of the codebase must remain usable and testable without
invoking a live LLM. Live-model calls must be isolated to the agent
layer and opt-in evaluation commands, never to standard unit or
integration tests.

## Rationale: Why LangGraph

LangGraph was chosen because the investigation loop has real state,
branching, and repeated tool calls, not because it is fashionable. A
hand-rolled loop was considered and rejected only because LangGraph's
checkpointing and observability were judged worth the added dependency.
This section is context, not a requirement.

## Out of Scope

Architecture-layer static rule checking (e.g. "routes may not call
repositories directly") is not implemented in V1 or V1.1. This document
does not define such rules.
