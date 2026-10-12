# SpecWatch — Updated Project Plan

## Review Addendum (2026-09-20)

Before implementation began, this plan was critically reviewed against the actual repository state (empty except this file) and the following changes were made. Everything not listed here stands as originally written.

**Component reclassification:**
- Evidence graph (§16) — the generic persisted graph/traversal abstraction is replaced with plain SQLite candidate tables (`requirement_candidates`, `test_candidates`) recomputed per analysis. No graph-traversal engine in V1.
- Agent tools (§8) — `compare_symbol_versions` is removed; its before/after semantics are folded into `inspect_diff`. `inspect_git_history` is promoted from "later" into V1 (needed for the rename/refactor disambiguation case). `search_architecture_rules` and `trace_execution_path` stay deferred — the latter can be composed by the agent via repeated `inspect_callers`/`inspect_callees` calls until eval shows that's insufficient.
- Requirement registry (§12–13) — V1 skips entity/behavior/constraint decomposition and supersession tracking; extraction produces statement + citation + stable ID only.
- PyTest index (§15) — V1 skips fixture/mock deep-parsing; keeps symbols, assertions, referenced symbols.
- Confidence model (§21) — V1 starts as a checklist-derived score from verifier checks, not a tuned multi-factor weighted formula (no data exists yet to calibrate weights).
- Feedback loop (§23) and architecture-layer drift (§3.4) are out of scope for V1 and V1.1; neither is required by the dogfooding demo list in §"Dogfooding Requirement".
- Code → spec drift (stale-spec, §3.2) is DEFERRED to a V1.1 milestone after spec→code and spec→test are proven — but not cut, since it's required for dogfood demo #5.

**Scope split:**
- **V1** (Phases 0–11): requirement registry, symbol index, pytest index, diff engine, impact filter, the trimmed 9-tool agent layer, LangGraph investigator, deterministic verifier, spec→code drift, spec→test evidence-gap. Covers dogfood demos #1 (violation), #2 (auth moved — no FP), #3 (harmless refactor — no flag), #4 (missing test evidence), #6 (ambiguous — abstain).
- **V1.1**: stale-spec detection (dogfood demo #5), GitHub Action, dogfood polish.

**Stack:** Correction (2026-09-20, Phase 8): `init_chat_model` lives in the separate `langchain` metapackage, not in `langchain-core` — it is *not* a free transitive dependency of LangGraph as originally assumed here. Instead, the investigator's model calls go through `langchain-core`'s own `BaseChatModel` interface directly (no wrapper class needed): the real provider is `langchain-anthropic`'s `ChatAnthropic` (a small, focused package — the concrete default), and a tiny in-repo factory (`create_chat_model(model: str) -> BaseChatModel`) maps a `"provider:model"` config string to the right small `langchain-<provider>` package, so swapping providers means installing that package and changing config, not code. Deterministic tests use `langchain-core`'s own `GenericFakeChatModel` (a scripted `AIMessage` iterator, tool_calls included) as the same `BaseChatModel` interface — no live API key needed for standard tests. No SQLAlchemy (raw `sqlite3` + small repository functions), no GitPython (subprocess + git CLI), no vector DB, `rank-bm25` for lexical requirement/code ranking.

Full review rationale (component-by-component KEEP/MODIFY/DEFER/REMOVE table, tool-by-tool review, static-analysis feasibility, evaluation design, risk ranking) was delivered in conversation and is not duplicated here.

---

## 0. Project Summary

**SpecWatch** is an agentic software auditor for detecting specification drift.

Its core job is:

> Determine whether a code change still matches the product requirements and architecture constraints that are supposed to govern the system.

Software teams commonly end up with multiple sources of truth:

- PRDs / product requirements
- architecture and design docs
- implementation
- tests

These sources drift apart over time. A requirement may still exist while the implementation changes, tests may stop covering important behavior, or architecture rules may quietly be violated.

SpecWatch is designed specifically for pull-request review.

It should not behave like a generic AI code reviewer.

The product should answer questions such as:

- Did this PR violate a documented requirement?
- Was behavior intentionally changed but the spec was not updated?
- Does the requirement exist without meaningful test evidence?
- Did this PR violate an architectural constraint?
- Is the situation ambiguous enough that more repository evidence must be gathered before making a claim?

The key design principle is:

> **The model gets agency over investigation. It does not get agency over truth.**

---

# 1. Product Thesis

A naive implementation would be:

```text
PRD + code diff
→ LLM
→ "Does anything look wrong?"
```

That is not SpecWatch.

SpecWatch should instead use:

```text
GitHub PR
   ↓
Deterministic preprocessing
   ├─ Git diff
   ├─ changed files
   ├─ changed symbols
   ├─ likely affected requirements
   └─ likely related tests
   ↓
Impact Filter
   ├─ obviously deterministic case → deterministic rule
   └─ ambiguous semantic case → Investigator Agent
                                      ↓
                              agent chooses tools
                                      ↓
                              gathers evidence
                                      ↓
                              forms hypothesis
                                      ↓
                           Deterministic Verifier
                                      ↓
                              PR finding / abstain
```

The agent should only be used when adaptive investigation is useful.

---

# 2. Why Agentic Architecture Actually Makes Sense

Different code changes require different investigations.

A fixed pipeline cannot always know in advance which context matters.

Example:

Requirement:

> Only authenticated project members may retrieve project documents.

A PR removes a local authorization check.

A naive system may immediately report:

> Authorization has been removed.

But the correct implementation may have moved authorization to:

- middleware
- a caller
- a decorator
- another service
- an API gateway
- a shared access-control layer

An investigator should be able to decide:

```text
I need to inspect callers.
↓
No check found.
↓
I should search middleware.
↓
Found authorization middleware.
↓
I should trace the execution path.
↓
All paths pass through the middleware.
↓
No violation.
```

Another change may be trivial.

Requirement:

> Password reset tokens expire after 30 minutes.

PR:

```python
TOKEN_TTL_MINUTES = 60
```

That should not require a long agent investigation.

The deterministic layer can resolve or directly escalate this simple contradiction.

Therefore:

> **Agentic reasoning is used for ambiguous evidence gathering, not as the default execution mechanism for every repository change.**

---

# 3. Core Drift Types

## 3.1 Spec → Code Drift

A requirement exists, but implementation changes may violate it.

Example:

```text
Requirement:
"External invoices require explicit operator approval before send."

PR:
Approval guard removed before outbound email.

Finding:
Possible requirement violation.
```

---

## 3.2 Code → Spec Drift

Behavior changed intentionally or materially, but the documentation still describes old behavior.

Example:

```text
Code:
retry_limit = 5

Spec:
"Failed sends are retried up to 3 times."
```

SpecWatch should surface:

```text
Possible stale specification.
```

---

## 3.3 Spec → Test Drift

A requirement exists but SpecWatch cannot find meaningful test evidence for the required behavior.

Example:

```text
Requirement:
"Non-members may not read project documents."

Tests found:
happy-path member access only

Finding:
No negative-access test evidence found.
```

Use careful wording.

Static analysis cannot prove that no test exists in every possible runtime path.

---

## 3.4 Architecture → Code Drift

Later phase.

Example architecture rule:

> API routes may call services but may not directly access repositories.

PR adds:

```python
await invoice_repository.get(...)
```

inside a route.

If the rule is deterministic, do not use an LLM.

---

# 4. Final High-Level Architecture

```text
                         GitHub PR
                             │
                             ▼
                    Deterministic Diff Engine
                             │
                             ▼
                     Changed Symbol Index
                             │
                             ▼
                    Requirement Impact Filter
                             │
                  ┌──────────┴──────────┐
                  │                     │
            obvious case          ambiguous case
                  │                     │
                  ▼                     ▼
          deterministic rule    LangGraph Investigator
                                        │
                          ┌─────────────┼─────────────┐
                          ▼             ▼             ▼
                    Requirement      Code Graph      Tests
                       Tools            Tools          Tools
                          │             │             │
                          ├─────────────┼─────────────┤
                          ▼             ▼             ▼
                    Git History   Architecture    Diff Evidence
                          │             │             │
                          └─────────────┴─────────────┘
                                        │
                                        ▼
                                Evidence Package
                                        │
                                        ▼
                              Deterministic Verifier
                              ├─ citations exist
                              ├─ file/line validation
                              ├─ evidence provenance
                              ├─ finding schema validation
                              ├─ confidence threshold
                              └─ duplicate suppression
                                        │
                           ┌────────────┴─────────────┐
                           ▼                          ▼
                     PR Finding                 No Finding /
                                              Insufficient Evidence
```

---

# 5. Agent Architecture

## Framework

Use **LangGraph** for the investigator.

Reason:

The investigation naturally has:

- graph state
- conditional branching
- repeated tool calls
- explicit termination conditions
- bounded loops
- deterministic verification after the model
- optional checkpointing
- optional human review later

Do not use LangGraph merely as a wrapper around one prompt.

The graph should represent a real investigation loop.

Initial graph:

```text
START
  ↓
Seed Evidence
  ↓
Investigator
  ↓
Need more evidence?
 ↙             ↘
YES             NO
↓                ↓
Tool Node      Finalize
↓                ↓
Investigator   Verify
  ↑              ↓
  └──────────   Report / Abstain
```

---

# 6. Do Not Start Multi-Agent

V1 should use:

```text
One Investigator Agent
+
strong domain-specific tools
+
deterministic verifier
```

Do not start with:

```text
SecurityAgent
TestAgent
ArchitectureAgent
RequirementsAgent
CoordinatorAgent
ReviewerAgent
```

That adds complexity without proving value.

Only split into specialist agents later if evaluation demonstrates that specialization materially improves:

- accuracy
- tool selection
- context efficiency
- reasoning quality
- maintainability

---

# 7. Investigator Responsibilities

The Investigator Agent may:

- decide what evidence it needs next
- call bounded repository-analysis tools
- compare competing hypotheses
- inspect nearby execution paths
- inspect test evidence
- inspect requirements
- inspect relevant Git history
- identify uncertainty
- stop when enough evidence exists
- explicitly return insufficient evidence

The Investigator Agent may NOT:

- access arbitrary filesystem paths
- mutate repository state
- edit source code
- post directly to GitHub
- fabricate citations
- decide whether its own citations are valid
- bypass tool limits
- bypass confidence thresholds

---

# 8. Agent Tools

Use domain-specific tools rather than giving the agent generic unrestricted filesystem access.

## 8.1 `search_requirements`

```python
search_requirements(
    query: str,
    limit: int = 10,
)
```

Returns:

- requirement IDs
- titles
- source files
- source ranges
- short statements
- scores

---

## 8.2 `inspect_requirement`

```python
inspect_requirement(
    requirement_id: str,
)
```

Returns:

- statement
- constraints
- source
- exact line range
- status
- related requirements
- supersession info

---

## 8.3 `search_code`

```python
search_code(
    query: str,
    limit: int = 10,
)
```

Search the indexed symbol registry.

Do not expose arbitrary recursive grep as the primary interface.

---

## 8.4 `inspect_symbol`

```python
inspect_symbol(
    qualified_name: str,
    revision: Literal["base", "head"],
)
```

Returns:

- source code
- file
- line range
- signature
- callers/callees summary
- imports
- metadata

---

## 8.5 `inspect_callers`

```python
inspect_callers(
    symbol: str,
    depth: int = 1,
)
```

Returns bounded caller relationships from the static call graph.

---

## 8.6 `inspect_callees`

```python
inspect_callees(
    symbol: str,
    depth: int = 1,
)
```

---

## 8.7 `inspect_diff`

```python
inspect_diff(
    file: str,
    symbol: str | None = None,
)
```

Returns bounded before/after evidence.

---

## 8.8 `compare_symbol_versions` — REMOVED (see Review Addendum)

Folded into `inspect_diff`, which accepts a `symbol` argument and returns old/new source plus a bounded unified hunk. A separate tool duplicated `inspect_diff` + `inspect_symbol(base)` + `inspect_symbol(head)` without adding capability.

---

## 8.9 `search_tests`

```python
search_tests(
    query: str | None = None,
    symbol: str | None = None,
    requirement_id: str | None = None,
    limit: int = 10,
)
```

---

## 8.10 `inspect_test`

```python
inspect_test(
    qualified_name: str,
)
```

Returns:

- exact source
- file/lines
- assertions
- referenced symbols
- fixtures
- mocks

---

## 8.11 `inspect_git_history` — PROMOTED TO V1 (see Review Addendum)

```python
inspect_git_history(
    symbol: str | None = None,
    file: str | None = None,
    limit: int = 5,
)
```

Useful when a suspicious change may represent an intentional refactor or relocation. Directly load-bearing for the "auth moved elsewhere" false-positive-trap case, so it ships with the first 9 tools rather than after.

Returns commit sha, message, and stat only — never full patches. `limit` is a hard cap, not a suggestion.

Do not dump large commit history into context.

---

## 8.12 `search_architecture_rules` — DEFERRED (see Review Addendum)

```python
search_architecture_rules(
    query: str,
)
```

Returns explicit architecture requirements and citations. Only relevant once architecture-layer drift (§3.4) is in scope, which V1 and V1.1 explicitly are not.

---

## 8.13 `trace_execution_path` — DEFERRED (see Review Addendum)

Later-but-important tool. In V1 the agent composes the same result itself via repeated `inspect_callers`/`inspect_callees` calls; add this only if evaluation shows manual multi-hop traversal is a real bottleneck.

```python
trace_execution_path(
    from_symbol: str,
    to_symbol: str,
    max_depth: int = 5,
)
```

Example:

```text
invoice_tool.send_invoice
→ InvoiceService.send
→ InvoiceDeliveryService.deliver
→ PostmarkClient.send_email
```

This helps answer questions such as:

> Is approval enforced anywhere between entry point and side effect?

---

# 9. Investigation State

LangGraph state should be explicit.

Example:

```python
class InvestigationState(TypedDict):
    investigation_id: str

    changed_symbols: list[str]
    candidate_requirement_ids: list[str]

    evidence_items: list[EvidenceItem]
    tool_history: list[ToolCallRecord]

    hypotheses: list[Hypothesis]

    remaining_tool_budget: int
    remaining_token_budget: int

    status: Literal[
        "investigating",
        "ready_to_finalize",
        "insufficient_evidence",
        "budget_exhausted",
    ]

    final_candidate: FindingCandidate | None
```

Do not hide critical state inside prompt strings.

---

# 10. Investigation Budget

Every investigation must be bounded.

Initial defaults:

```text
max tool calls: 10
max investigation rounds: 3
max retrieved evidence tokens: configurable
max execution time: configurable
```

The exact values should be tuned using evaluation rather than treated as permanent constants.

The agent should be allowed to terminate with:

```text
INSUFFICIENT_EVIDENCE
```

A production-quality system should not force a confident answer.

---

# 11. Deterministic Preprocessing

Before invoking the agent:

## 11.1 Parse Git Diff

Determine:

- changed files
- changed line ranges
- added/removed lines
- renamed files

## 11.2 Map Diff to Symbols

Determine:

- functions changed
- classes changed
- methods changed
- symbols added
- symbols removed

## 11.3 Candidate Requirement Mapping

Find likely impacted requirements using:

- existing evidence mappings
- explicit references
- lexical similarity
- path hints
- call graph proximity

## 11.4 Candidate Test Mapping

Find likely related tests.

## 11.5 Impact Filter

Do not invoke the agent if there is no meaningful requirement/architecture relationship.

Also avoid agent invocation when a deterministic rule can resolve the case safely.

---

# 12. Requirement Extraction

Input:

```markdown
### Invoice Approval

All external invoices must be explicitly approved by the operator before they are sent.
```

Output:

```json
{
  "title": "Invoice Approval",
  "statement": "All external invoices must be explicitly approved by the operator before they are sent.",
  "entities": ["invoice", "operator"],
  "behaviors": ["send invoice"],
  "constraints": ["operator approval must occur before external send"]
}
```

Pipeline:

```text
Markdown
↓
section segmentation
↓
candidate classification
↓
structured LLM extraction
↓
citation validation
↓
normalization
↓
stable requirement ID
↓
Requirement Registry
```

Classify passages:

```text
REQUIREMENT
ARCHITECTURE_RULE
CONTEXT
EXAMPLE
NON_GOAL
OUT_OF_SCOPE
DESIGN_RATIONALE
```

Only active requirements and architecture rules should drive findings.

---

# 13. Stable Requirement Registry

Requirement IDs should not depend solely on line number.

Use a stable fingerprint derived from:

- normalized statement
- heading/context
- source document identity

Example:

```text
REQ-A13F92
```

Track:

- active
- superseded
- deprecated

Later:

```text
REQ-123 v1
→ REQ-123 v2
```

---

# 14. Python Static Analysis

Use Python AST initially.

Extract:

- modules
- classes
- functions
- methods
- decorators
- imports
- function calls
- docstrings
- constants
- source ranges
- qualified names

Example:

```text
app.services.invoice_service.InvoiceService.send_invoice
```

Build an approximate call graph.

Do not attempt perfect whole-program analysis in V1.

The objective is useful evidence retrieval, not formal verification.

Later consider:

- `libcst`
- `astroid`
- tree-sitter
- runtime coverage

only if needed.

---

# 15. PyTest Index

Extract:

- test functions
- fixtures
- imports
- referenced symbols
- assertions
- mocked calls
- exception assertions

Map tests to implementation using:

- direct calls
- imports
- explicit references
- lexical matching
- call graph relations

Later integrate `coverage.py` if runtime test-to-code mappings materially improve accuracy.

---

# 16. Evidence Graph — MODIFIED (see Review Addendum)

V1 does not build a generic persisted graph/traversal engine. Instead, `requirement_candidates` and `test_candidates` are plain SQLite tables recomputed per analysis run (requirement_id/symbol_id/score/method), with high-confidence explicit references persisted so the whole repository isn't rediscovered every PR. The relationships below describe the *conceptual* model these tables encode — they are not implemented as a general graph abstraction unless a later phase demonstrates the tables are insufficient.

Conceptual relationships:

```text
Requirement
   │
   ├── IMPLEMENTED_BY ──> CodeSymbol
   ├── TESTED_BY ───────> TestSymbol
   ├── RELATED_TO ──────> Requirement
   └── SUPERSEDES ──────> Requirement

CodeSymbol
   │
   ├── CALLS ───────────> CodeSymbol
   ├── CALLED_BY ───────> CodeSymbol
   └── TESTED_BY ───────> TestSymbol
```

Example model:

```python
class EvidenceEdge(BaseModel):
    source_id: str
    target_id: str
    relationship: str
    confidence: float

    method: Literal[
        "explicit_reference",
        "static_analysis",
        "lexical",
        "llm",
        "manual",
    ]

    evidence: list[str]
```

Persist high-quality relationships so the entire repository does not need to be rediscovered on every PR.

---

# 17. Candidate Mapping

Do not ask an LLM to compare every requirement with every symbol.

Use deterministic candidate generation first.

Signals:

- lexical overlap
- symbol names
- file paths
- explicit references
- call graph neighborhood
- existing evidence edges

Then optionally ask the model to rank a small candidate set.

Example:

```text
requirement
+
top 8 candidate symbols
→ structured relevance ranking
```

Add embeddings only if evaluation shows they improve retrieval enough to justify them.

Do not add a vector database by default.

---

# 18. Investigator Loop

The main agent loop:

```text
1. Receive seed evidence
2. Form one or more hypotheses
3. Identify missing evidence
4. Choose a tool
5. Inspect returned evidence
6. Update hypothesis
7. Repeat until:
   - enough evidence exists
   - evidence disproves concern
   - evidence remains insufficient
   - budget is exhausted
8. Produce structured FindingCandidate
```

The model should be encouraged to disconfirm its own hypothesis.

Example:

```text
Hypothesis:
"Authorization may have been removed."

Required investigation:
- caller authorization?
- middleware authorization?
- decorator?
- replacement access-control function?
- negative tests?
```

This is important for reducing false positives.

---

# 19. Finding Candidate Schema

The agent must return structured output.

```python
class FindingCandidate(BaseModel):
    verdict: Literal[
        "spec_violation_likely",
        "spec_may_be_stale",
        "test_evidence_gap",
        "architecture_violation_likely",
        "no_issue",
        "insufficient_evidence",
    ]

    requirement_ids: list[str]
    changed_symbol_ids: list[str]

    summary: str
    reasoning: str

    citations: list[Citation]

    unresolved_questions: list[str]

    model_confidence: float
```

This is only a candidate.

It must still pass verification.

---

# 20. Deterministic Verifier

The verifier is not another LLM agent.

It should validate:

## Citation Validity

- file exists
- line numbers exist
- cited lines were actually retrieved
- quoted evidence matches source

## Evidence Provenance

Every claim must derive from:

- repository source
- registered requirement
- Git data
- test data
- architecture configuration

## Schema Validity

Required fields exist and use valid IDs.

## Confidence Threshold

Do not publish low-confidence findings.

## Deduplication

Collapse findings with the same:

```text
requirement
+
subsystem
+
drift type
```

## Publication Policy

Allow:

```text
publish
suppress
abstain
```

---

# 21. Confidence Model

Do not trust the model's self-reported confidence alone.

Possible factors:

```text
requirement ↔ code mapping strength
changed-symbol relevance
evidence completeness
execution-path evidence
test evidence
model verdict confidence
citation completeness
```

Start conservatively.

Suggested initial PR publication threshold:

```text
>= 0.80
```

Tune with evaluations.

Precision should be prioritized before recall.

---

# 22. User-Facing GitHub Experience

A useful PR comment might look like:

```text
SpecWatch

1 possible specification conflict found.

AUTH-004 — Users may only access organizations they belong to

Changed behavior:
OrganizationService.get_documents() no longer performs
a local membership check.

Investigation:
✓ inspected changed symbol
✓ inspected 3 callers
✓ searched authorization middleware
✓ inspected related tests
✗ no equivalent authorization guard found

Evidence:
docs/security.md:31-34
src/services/organization_service.py:88-112

Test evidence:
No non-member access case was found in the related tests.

Confidence: High

Feedback:
[Valid] [False positive] [Expected change] [Spec is outdated]
```

The report should show enough investigation detail to earn trust without dumping model chain-of-thought.

---

# 23. Feedback Loop

Allow developers to classify a finding:

```text
valid
false_positive
expected_change
spec_is_outdated
```

Persist feedback.

Use it later to:

- suppress duplicate dismissed findings
- tune confidence thresholds
- improve requirement mappings
- identify repeatedly stale requirements

Do not automatically rewrite specs or code.

---

# 24. GitHub Integration

## V1

Use GitHub Actions.

Workflow:

```text
pull_request
↓
checkout repository with sufficient history
↓
install SpecWatch
↓
index/update repository state
↓
analyze base...head
↓
publish GitHub job summary
↓
create/update one PR comment if findings exist
```

Prefer a single summary comment initially.

## Later

GitHub App for:

- easier installation
- central authentication
- richer PR interactions
- organization-wide configuration
- feedback collection

Do not build this before the engine proves useful.

---

# 25. CLI

Initial commands:

```bash
specwatch config validate
specwatch index
specwatch requirements list
specwatch requirements show REQ-123
specwatch diff --base HEAD~1
specwatch analyze --base main --head HEAD
specwatch explain SW-123
```

Useful debugging command later:

```bash
specwatch investigate SW-123 --show-tools
```

This may show tool events and evidence retrieval, but never hidden model chain-of-thought.

---

# 26. Recommended Stack

## Core

- Python 3.12+
- Pydantic
- Typer
- SQLite initially
- PyTest

## Agent

- LangGraph
- `langchain-anthropic`'s `ChatAnthropic`, used directly through `langchain-core`'s `BaseChatModel` interface (see the Stack correction above) — a small in-repo factory maps a config string to the right provider class. Defined in `agent/` only; never imported by domain/services/verification code.
- `rank-bm25` for lexical requirement/code candidate ranking (no vector DB, no embeddings in V1)

Do not make the rest of the application dependent on LangChain/LangGraph abstractions unnecessarily — tools call plain, independently-testable Python services.

## Static Analysis

- Python `ast`
- Git CLI via `subprocess` (no GitPython)

Potential later:
- `libcst`
- `coverage.py`
- tree-sitter

## CI

- GitHub Actions

## Storage

SQLite for MVP, accessed via stdlib `sqlite3` and small repository functions — no SQLAlchemy/ORM in V1; the table set is small enough that an ORM is premature abstraction.

Design repositories so Postgres can be introduced later if a hosted service becomes necessary.

---

# 27. Suggested Repository Structure

```text
specwatch/
├── README.md
├── PLAN.md
├── pyproject.toml
├── specwatch.yml
│
├── docs/
│   ├── product-prd.md
│   └── architecture.md
│
├── src/specwatch/
│   ├── cli.py
│   ├── config.py
│   │
│   ├── domain/
│   │   ├── models.py
│   │   ├── enums.py
│   │   └── errors.py
│   │
│   ├── specs/
│   │   ├── parser.py
│   │   ├── extractor.py
│   │   ├── registry.py
│   │   └── supersession.py
│   │
│   ├── code/
│   │   ├── python_parser.py
│   │   ├── symbol_index.py
│   │   ├── call_graph.py
│   │   └── path_tracer.py
│   │
│   ├── tests_index/
│   │   ├── pytest_parser.py
│   │   └── mapper.py
│   │
│   ├── mapping/
│   │   ├── candidate_generator.py
│   │   ├── requirement_mapper.py
│   │   └── evidence_graph.py
│   │
│   ├── git/
│   │   ├── client.py
│   │   ├── diff.py
│   │   └── history.py
│   │
│   ├── agent/
│   │   ├── graph.py
│   │   ├── state.py
│   │   ├── investigator.py
│   │   ├── prompts.py
│   │   └── tools/
│   │       ├── requirements.py
│   │       ├── code.py
│   │       ├── tests.py
│   │       ├── git.py
│   │       └── architecture.py
│   │
│   ├── verification/
│   │   ├── citations.py
│   │   ├── provenance.py
│   │   ├── confidence.py
│   │   └── dedupe.py
│   │
│   ├── storage/
│   │   ├── db.py
│   │   └── repositories.py
│   │
│   └── reporting/
│       ├── console.py
│       └── github.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   ├── fixtures/
│   └── evals/
│
└── examples/
    └── demo_repo/
```

Do not create every file immediately.

Only create modules needed by the current phase.

---

# 28. Evaluation Strategy

This project must evaluate both:

1. final findings
2. agent investigation behavior

Build a benchmark repository.

Each case should contain:

```text
spec
base implementation
changed implementation
tests
expected verdict
required evidence
```

## Positive cases

- authorization guard removed
- approval check removed
- validation bypassed
- required audit event removed
- privacy filter removed
- documented timeout changed

## False-positive traps

- authorization moved upstream
- authorization moved into middleware
- helper function renamed
- logic refactored but behavior preserved
- test renamed
- function moved to another module
- wrapper removed while equivalent guard remains elsewhere

These cases are extremely important because they justify agentic investigation.

## Stale-spec cases

- behavior intentionally changed
- docs were not updated

## Test-gap cases

- requirement exists
- implementation exists
- important negative case is not represented in related tests

## Ambiguous cases

Expected verdict:

```text
insufficient_evidence
```

---

# 29. Agent Evaluation Metrics

Track:

## Final-output metrics

- precision
- recall
- F1
- false-positive rate
- false-negative rate
- citation-validity rate

## Investigation metrics

- evidence recall
- irrelevant retrieval rate
- average tool calls
- average investigation rounds
- token usage
- time per investigation
- successful abstention rate
- unnecessary-agent-invocation rate

Important metric:

> Did the agent retrieve the evidence required to disprove an initially suspicious hypothesis?

Example:

A local auth check disappeared, but middleware now handles authorization.

The agent should find the middleware instead of generating a false positive.

---

# 30. Self-Dogfooding

SpecWatch should monitor SpecWatch itself.

Example requirement:

> Findings below the configured publication threshold must not be posted to GitHub.

Implementation:

```python
if finding.confidence >= config.min_confidence:
    post_finding(finding)
```

Create intentional PR:

```python
if finding.confidence >= 0.40:
    post_finding(finding)
```

Expected:

```text
POSSIBLE SPEC DRIFT

Requirement:
Findings below configured publication threshold must not be posted.

Changed:
src/specwatch/reporting/github.py

Evidence:
The new condition hardcodes 0.40 instead of the configured threshold.

Confidence: High
```

Also create an ambiguous dogfood case where behavior moves elsewhere and force the Investigator Agent to find it.

---

# 31. Testing Strategy

## Unit Tests

- Markdown segmentation
- requirement extraction schemas
- stable IDs
- AST symbol extraction
- call graph construction
- diff mapping
- test parsing
- evidence graph
- every agent tool
- citation validation
- confidence calculation
- deduplication

## Integration Tests

```text
PRD
→ requirement registry
→ symbol index
→ diff
→ candidate requirements
→ investigator
→ verifier
→ finding
```

## Agent Tool Tests

Every tool should have:

- normal path
- missing target
- invalid ID
- result-size bound
- line-range correctness

## End-to-End Tests

Create temporary Git repositories:

```text
git init
→ baseline commit
→ changed commit
→ run SpecWatch
→ assert findings
```

## LLM Evals

Keep ordinary tests deterministic.

Use a separate opt-in live eval suite for:

- requirement extraction
- tool selection
- hypothesis revision
- drift classification
- abstention behavior

---

# 32. Security / Privacy

SpecWatch may run against private source code.

This matters.

Requirements:

- explicit `.specwatchignore`
- never read `.env`
- never intentionally load credentials
- bound tool results
- document which repository content is sent to model provider
- avoid logging raw sensitive source unnecessarily
- support provider configuration

Later:

- local models
- enterprise-hosted models
- redaction
- organization policies

Agent must not have unrestricted shell or filesystem access.

Expose narrow, validated tools.

---

# 33. Failure Modes

## False Positives

Highest product risk.

Mitigate using:

- agentic disconfirmation
- bounded evidence retrieval
- high confidence threshold
- deterministic validation
- user feedback
- abstention

## False Negatives

Accept some early.

Do not destroy trust by flooding users.

## Agent Wandering

Prevent with:

- tool budgets
- round budgets
- bounded results
- deterministic termination conditions

## Hallucinated Evidence

Prevent by:

- tool-generated IDs
- citation validation
- no arbitrary citations
- reject unsupported finding

## Huge Repositories

Use:

- incremental indexing
- changed-symbol filtering
- evidence graph
- candidate retrieval

Never repeatedly send entire repository.

## Weak Specs

If the requirement itself is ambiguous:

```text
INSUFFICIENT_EVIDENCE
```

or:

```text
SPEC MAY REQUIRE CLARIFICATION
```

Do not invent product intent.

---

# 34. Implementation Phases

## Phase 0 — Bootstrap

Build:

- project package
- `pyproject.toml`
- CLI
- config
- logging
- SQLite
- base domain models
- PyTest setup

Acceptance:

```bash
specwatch --help
specwatch config validate
```

work.

Do not add LangGraph logic yet beyond dependency planning.

---

## Phase 1 — Requirement Registry

Build:

- Markdown parser
- section segmentation
- requirement classification
- structured requirement extraction
- exact source citations
- stable IDs
- persistence

Acceptance:

- sample PRD produces useful requirements
- all requirements cite exact source
- unrelated line movement does not change IDs

---

## Phase 2 — Python Symbol Index

Build:

- AST parsing
- symbol registry
- qualified names
- source ranges
- imports
- calls
- hashes

Acceptance:

- fixture repo indexed correctly

---

## Phase 3 — PyTest Index

Build:

- test symbols
- fixtures
- assertions
- implementation references
- initial test mappings

---

## Phase 4 — Evidence Graph

Build:

```text
requirements ↔ code
requirements ↔ tests
code ↔ tests
code ↔ code
```

Start with deterministic signals.

Add small-model/LLM ranking only where necessary.

---

## Phase 5 — Git Diff + Changed Symbol Analysis

Build:

- base/head diff
- changed files
- changed line ranges
- changed symbols
- additions/removals
- renames where possible

Acceptance:

```bash
specwatch diff --base HEAD~1
```

returns the correct symbols.

---

## Phase 6 — Deterministic Impact Filter

Before building the agent, decide:

- which changed symbols have relevant requirements
- which cases can be handled deterministically
- which cases need semantic investigation

Acceptance:

A harmless unrelated code change should not invoke the Investigator Agent.

---

## Phase 7 — Agent Tool Layer

Implement and test (V1 set of 9 — see Review Addendum for the removal of `compare_symbol_versions` and promotion of `inspect_git_history`):

- `search_requirements`
- `inspect_requirement`
- `search_code`
- `inspect_symbol`
- `inspect_callers`
- `inspect_callees`
- `inspect_diff` (includes before/after semantics)
- `search_tests`
- `inspect_test`
- `inspect_git_history`

Later add (only if evaluation shows they're needed):

- `search_architecture_rules`
- `trace_execution_path`

Every tool must return bounded structured data.

---

## Phase 8 — LangGraph Investigator

Implement:

```text
seed
→ investigator
→ tool
→ investigator
→ ...
→ finalize
```

Include:

- explicit state
- max tool calls
- max rounds
- structured output
- `insufficient_evidence`
- deterministic termination

Acceptance:

Agent can investigate a seeded auth-removal scenario and find whether equivalent enforcement exists elsewhere.

---

## Phase 9 — Deterministic Verifier

Build:

- citation validation
- evidence provenance
- schema validation
- confidence calculation
- deduplication
- publication rules

No candidate may reach reporting without verification.

---

## Phase 10 — Spec → Code Drift

End-to-end first product capability.

Acceptance cases:

1. removed approval guard → finding
2. authorization moved to middleware → no finding
3. harmless rename → no finding
4. ambiguous change → insufficient evidence

---

## Phase 11 — Spec → Test Evidence

Add test-gap analysis.

Keep output conservative.

---

## Phase 12 — Code → Spec Drift

Add stale-document detection.

This is harder.

Only proceed after Spec → Code performance is acceptable.

---

## Phase 13 — GitHub Action

Build:

- pull-request workflow
- Markdown findings
- single summary comment
- job summary

---

## Phase 14 — Dogfood SpecWatch

Run SpecWatch on its own repository.

Create polished demo cases.

---

# 35. Later Roadmap

After core system is proven:

- `trace_execution_path`
- runtime test mapping with `coverage.py`
- architecture-layer rules
- requirement supersession
- contradictory requirements
- TypeScript support
- GitHub App
- organization dashboards
- IDE integration
- PDF / Google Docs specs
- hosted Postgres
- optional specialist agents if evaluations justify them

---

# 36. Non-Goals

Do not turn SpecWatch into:

- generic code review
- repository chatbot
- autonomous coding agent
- code-fixing bot
- PR summarizer
- documentation generator
- linter replacement
- static analyzer replacement
- test generator

The wedge is:

> **Agentically investigate whether changed code still satisfies explicit software requirements.**

---

# 37. Product Positioning

Do not say:

> AI reviews your PRs.

Say:

> **Know when your implementation stops matching your spec.**

More technical version:

> SpecWatch is an agentic software auditor that starts from changed symbols in a pull request, selectively investigates requirements, code paths, tests, Git history, and architecture evidence, then reports only citation-backed specification drift.

---

# 38. What Makes the Project Technically Strong

The implementation should create meaningful engineering decisions around:

- LangGraph
- tool-calling agents
- bounded agent loops
- agent evaluation
- AST parsing
- static analysis
- call graphs
- Git internals
- requirement extraction
- graph modeling
- incremental computation
- candidate retrieval
- provenance
- hallucination prevention
- citation validation
- test mapping
- CI/CD
- false-positive control
- caching
- persistence
- security/privacy
- deterministic vs probabilistic boundaries

If the final architecture becomes:

```text
PRD + diff → Claude → GitHub comment
```

the project has failed.

---

# 39. Resume Outcome

Only if supported by the finished implementation:

> Built an agentic GitHub auditor that investigates specification drift by autonomously querying repository tools for requirements, call graphs, tests, Git history, and architecture evidence before surfacing citation-backed PR findings.

> Built a static-analysis and evidence-graph layer linking natural-language requirements to Python symbols and PyTest coverage, allowing a LangGraph investigator to adaptively gather only the context needed for each code change.

> Designed deterministic citation, provenance, confidence, and deduplication checks around LLM-generated findings to reduce false positives and prevent unsupported claims from reaching pull requests.

---

# 40. Instructions for Claude Code

Before writing code, read this entire plan.

Then first respond with:

1. your understanding of SpecWatch
2. why agentic architecture is justified here
3. which parts must remain deterministic
4. the largest technical risks
5. potential flaws in this plan
6. exact initial dependencies
7. proposed Phase 0 repository structure
8. what you will explicitly NOT build yet
9. Phase 0 acceptance criteria

Implementation rules:

1. Work one phase at a time.
2. Do not create the whole file tree upfront.
3. Before each phase:
   - inspect existing code
   - explain intended changes
   - list schema changes
   - list dependencies
   - define tests
4. Prefer deterministic analysis over LLM reasoning whenever the problem is deterministic.
5. Use the Investigator Agent only for ambiguous semantic investigation.
6. Keep the initial design single-agent.
7. Use LangGraph because the investigation loop genuinely requires state, tools, branching, and termination.
8. Every agent tool must expose bounded structured results.
9. Do not give the agent unrestricted filesystem, shell, GitHub, or code-mutation access.
10. Use structured schemas for all model outputs.
11. Never trust model-generated citations without deterministic validation.
12. Support explicit `insufficient_evidence`.
13. Make tool-call and investigation budgets configurable.
14. Keep standard tests deterministic; use live-model calls only in opt-in evals.
15. Optimize precision before recall.
16. Build false-positive traps into the evaluation suite early.
17. Do not add a vector database until evaluation shows it is necessary.
18. Do not add a frontend before the core analysis engine works.
19. Do not add microservices.
20. Do not add specialist agents unless measured results justify them.
21. Do not add autonomous code modification.
22. Dogfood SpecWatch on SpecWatch.
23. Update this plan when implementation proves an assumption wrong.
