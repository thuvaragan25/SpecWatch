# SpecWatch Product Requirements

This document describes SpecWatch's own behavioral requirements, used to
dogfood SpecWatch against its own repository (plan.md's Dogfooding
Requirement). These are real, extractable requirements about the actual
codebase, not illustrative examples.

## Publication Threshold

A finding must not be published unless its computed confidence meets or
exceeds the configured minimum confidence threshold. Findings below the
configured publication threshold must not be posted to GitHub.

## Default Publication Threshold Value

The publication confidence threshold shall default to 0.80 unless
explicitly configured otherwise in `specwatch.yml`.

## Citation Integrity

A finding must only cite evidence that was actually retrieved by a tool
call during its own investigation. The verifier must reject any finding
whose citation references an evidence ID that was not retrieved this
investigation.

## Investigation Budget

The Investigator must not exceed the configured maximum number of tool
calls or investigation rounds, even if it has not reached a conclusion.
When a budget is exhausted, the investigation must terminate with
insufficient_evidence rather than continue.

## Requirement Extraction Determinism

Extracting requirements from the same specification document twice must
produce the same requirement IDs, regardless of unrelated line movement
elsewhere in the document.

## Abstention

When the Investigator's evidence is genuinely insufficient or the
situation is ambiguous, it must return insufficient_evidence rather than
guessing at a verdict.

## PR-Only Comment Posting

The `specwatch analyze --post-github` command must not attempt to post a
pull-request comment when the GitHub Actions event is not a pull_request
event.

## Non-Goals

SpecWatch is not a general-purpose code review tool, a repository
chatbot, or an autonomous code-fixing agent. It does not modify source
code or specification documents automatically.
