# SpecWatch

**An agentic specification-drift auditor for pull requests.**

SpecWatch reads your written requirements (a Markdown spec/PRD), watches what a pull request changes in the code, and tells you when the change **breaks a requirement**, leaves a requirement **without test evidence**, or makes a requirement **out of date**.

It is not a linter and not a generic code reviewer. It answers one question: *does this change still match what we said the system should do?*

---

## What it detects

| Verdict | Meaning |
|---|---|
| `spec_violation_likely` | The change makes the code contradict a requirement. |
| `test_evidence_gap` | A requirement (typically a prohibition such as "must not…") has no test that exercises it. |
| `spec_may_be_stale` | The code changed deliberately and correctly, but the requirement still describes the old behavior. |
| `no_issue` / `insufficient_evidence` | Not published. SpecWatch abstains rather than guess. |

Findings are only posted when they pass a deterministic verifier (see [How it works](#how-it-works)). A missed subtle issue is treated as better than a false alarm.

## Example output

```
SpecWatch

1 possible specification conflict(s) found.

### Spec Violation Likely
Requirement(s): REQ-929C64

The change disables expiration validation in `_validate_exp` by setting the
condition to `False and ...`, so ExpiredSignatureError can never be raised.

Evidence:
- docs/spec.md:3-4
- jwt/api_jwt.py:512-513
- tests/test_api_jwt.py:515-532

Confidence: Very High (1.00)
```

---

## Quick start

### Requirements

- Python 3.12+ (developed on 3.14) and [uv](https://docs.astral.sh/uv/)
- git
- An API key for a supported model provider (see [Choosing a model](#choosing-a-model))
- A **Python** target repository (the code and pytest indexes are Python-only)
- A Markdown spec for that repository

### Install

```bash
git clone <this repo> ~/SpecWatch
cd ~/SpecWatch
uv sync
```

### Run it on a repository

```bash
cd /path/to/target-repo
export ANTHROPIC_API_KEY=...        # or GROQ_API_KEY / GOOGLE_API_KEY, see below

# 1. Extract requirements from your spec and index the code and tests
uv run --project ~/SpecWatch specwatch index --spec path/to/spec.md

# 2. (optional, no model call) see what a branch changes
uv run --project ~/SpecWatch specwatch diff --base main --head my-branch

# 3. Analyze the change against the requirements
uv run --project ~/SpecWatch specwatch analyze --base main --head my-branch
```

`--spec` accepts any Markdown file path; it does not have to live inside the target repo. SpecWatch writes its state to `.specwatch/` in the target repo (add it to `.gitignore`).

---

## Writing a spec SpecWatch can read

Requirement extraction is **deterministic**, not LLM-based, so the spec needs a recognizable shape:

- One requirement per Markdown **heading**, with the statement in the body.
- Use obligation words in the body: `must`, `must not`, `shall`, `may not`, `required to`, `should`.
- Name the concrete things involved (functions, exceptions, config keys). Matching to code starts from the spec's wording.
- Sections whose heading contains `Non-goals`, `Out of scope`, `Example`, `Rationale`, or `Motivation` are not extracted as requirements.
- Headings containing `Architecture`, `Layering`, or `Design constraint` are extracted as architecture rules.

```markdown
## Expiration
A token whose exp claim is in the past must be rejected with
ExpiredSignatureError when decoding with expiration verification enabled.

## Non-goals
The library does not implement JWE encryption.
```

Each requirement gets a stable ID (`REQ-XXXXXX`) derived from its document, heading, and statement. Inspect them with:

```bash
specwatch requirements list
specwatch requirements show REQ-929C64
```

---

## Configuration

Create `specwatch.yml` in the target repository root (all keys optional):

```yaml
model: anthropic:claude-sonnet-5-5   # provider:model
min_confidence: 0.80                 # publication threshold, 0.0-1.0
max_tool_calls: 8                    # per investigation
max_rounds: 4                        # model calls per investigation
```

Validate it with `specwatch config validate`.

### Choosing a model

The `model` value is `provider:model-name`.

| Provider | Example | Env var | Notes |
|---|---|---|---|
| `anthropic` | `anthropic:claude-sonnet-5-5` | `ANTHROPIC_API_KEY` | The default and the intended provider. Paid, prepaid credits. |
| `groq` | `groq:openai/gpt-oss-120b` | `GROQ_API_KEY` | Free tier exists but its token caps are too small for multi-round investigations. |
| `google` | `google:gemini-3.6-flash` | `GOOGLE_API_KEY` | Free tier is limited to roughly 20 requests per model per day, so a handful of investigations per day. |

Adding a provider is one branch in `src/specwatch/agent/provider.py` plus its `langchain-<provider>` package.

Weaker or small-context models may need more headroom than the defaults; raise `max_tool_calls` and `max_rounds` (for example 14 and 12).

---

## GitHub Action

`.github/workflows/specwatch.yml` runs SpecWatch on every pull request: it indexes the repo, analyzes `base...head`, writes a job summary, and creates or updates a single PR comment when there are findings. It needs an `ANTHROPIC_API_KEY` repository secret.

---

## How it works

```
spec (Markdown)  ──►  requirement registry (stable IDs)
                               │
git base...head  ──►  changed-symbol analysis (AST, normalized body hashes)
                               │
           candidate mapping: requirement ⇄ code ⇄ tests
           (BM25 lexical match + one-hop expansion through callers)
                               │
              impact filter  ──  no linked requirement? stop, no model call
                               │
        evidence prefetch  (diff, requirement text, candidate tests)
                               │
        investigator agent (LangGraph, bounded tools and rounds)
                               │
        deterministic verifier  ──►  published finding, or abstain
```

1. **Deterministic first.** Parsing, symbol and call-graph indexing, pytest indexing, diffing, and candidate mapping involve no model. Most pull requests never reach the model: if a changed symbol has no linked requirement, SpecWatch stops there.
2. **Agent second.** For a changed symbol with linked requirements, a bounded investigator agent gathers evidence with a fixed tool set: `search_requirements`, `inspect_requirement`, `search_code`, `inspect_symbol`, `inspect_callers`, `inspect_callees`, `inspect_diff`, `search_tests`, `inspect_test`, and `inspect_git_history`. Common evidence is prefetched so most investigations take only 2 to 6 model calls. The agent is told to try to disprove its first hypothesis, for example by looking for a moved or equivalent check, before concluding.
3. **Verification last.** The model never decides what gets posted. A deterministic verifier checks that every citation refers to evidence actually retrieved this investigation, that the cited file appears in that evidence, and that the quoted text exists verbatim at the cited lines. It then computes confidence from checklist results and applies the publication threshold. A finding that fails any check is suppressed.

### Design principles

- Prefer abstaining to guessing.
- The model has agency over *investigation*, not over *publication*.
- Everything citable must be real: file, line range, and quote.
- Unresolved calls in the static call graph are kept as "something may be here," never treated as "nothing is here."

---

## Commands

| Command | Purpose |
|---|---|
| `specwatch index --spec FILE` | Extract requirements, index code and tests, build candidate mappings. |
| `specwatch diff --base REV [--head REV]` | Show changed Python files and symbols. No model call. |
| `specwatch analyze --base REV [--head REV] [--post-github]` | Full pipeline. `--post-github` also writes the job summary and PR comment (needs `GITHUB_TOKEN`, `GITHUB_REPOSITORY`, `GITHUB_EVENT_PATH`, all set automatically inside a `pull_request` workflow). |
| `specwatch requirements extract\|list\|show` | Work with the requirement registry. |
| `specwatch config validate` | Validate `specwatch.yml`. |
| `specwatch -v ...` | Verbose logging. |

---

## Features

requirement registry, Python symbol and call-graph index, pytest index, candidate mapping, git diff and changed-symbol analysis, impact filter, agent tool layer, LangGraph investigator, deterministic verifier, spec→code drift, spec→test evidence gap, code→spec staleness detection, GitHub Action workflow, and self-dogfooding (`docs/product-prd.md`). The suite has 230 passing tests, all deterministic and offline (a scripted fake model stands in for the LLM).

---

## Development

```bash
uv sync
uv run pytest                 # 230 tests, offline and deterministic
uv run specwatch --help
```

Repository layout:

```
src/specwatch/
  specs/         requirement parsing, extraction, stable IDs
  code/          Python AST parser, symbol index, call graph
  tests_index/   pytest test index
  git/           diff and changed-symbol analysis
  mapping/       candidate generation, test-gap and stale-spec heuristics
  impact_filter.py   decides which changes reach the agent
  agent/         LangGraph investigator, tools, prompts, provider factory
  verification/  citation checks, confidence, dedupe, publication policy
  reporting/     Markdown and GitHub output
  storage/       SQLite repositories
  cli.py         Typer CLI
tests/           unit, integration, and fixture repositories
docs/            architecture.md and product-prd.md (SpecWatch's own spec)
plan.md          full project plan and implementation phases
```

Standard tests never call a live model. Live-model checks are run by hand against real repositories.

### Dogfooding

`docs/product-prd.md` states SpecWatch's own behavioral requirements. Run SpecWatch against its own pull requests with:

```bash
specwatch index --spec docs/product-prd.md
specwatch analyze --base main --head HEAD
```

---

## Further reading

- [`plan.md`](plan.md): full design, agent architecture, phases, and evaluation strategy
- [`docs/architecture.md`](docs/architecture.md): architecture notes
- [`docs/product-prd.md`](docs/product-prd.md): SpecWatch's own requirements

## License

[MIT](LICENSE)
