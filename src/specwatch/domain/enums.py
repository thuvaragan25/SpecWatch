"""Shared enumerations for SpecWatch domain models."""

from enum import Enum


class RequirementStatus(str, Enum):
    """Lifecycle status of a requirement in the registry."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DEPRECATED = "deprecated"


class PassageType(str, Enum):
    """Classification of a segmented spec-document passage.

    Only REQUIREMENT and ARCHITECTURE_RULE passages are turned into
    registry entries that can drive findings.
    """

    REQUIREMENT = "requirement"
    ARCHITECTURE_RULE = "architecture_rule"
    CONTEXT = "context"
    EXAMPLE = "example"
    NON_GOAL = "non_goal"
    OUT_OF_SCOPE = "out_of_scope"
    DESIGN_RATIONALE = "design_rationale"


class SymbolKind(str, Enum):
    """Kind of a code symbol in the Python symbol index."""

    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    CONSTANT = "constant"


class CandidateMethod(str, Enum):
    """How a requirement<->code/test candidate link was generated."""

    LEXICAL = "lexical"
    STATIC_ANALYSIS = "static_analysis"


class FileChangeType(str, Enum):
    """How a file changed between base and head."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


class SymbolChangeType(str, Enum):
    """How a symbol changed between base and head.

    Determined by comparing body_hash, not text diffing -- a symbol whose
    body_hash is unchanged is not reported even if its file moved.
    """

    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"


class FindingVerdict(str, Enum):
    """The Investigator's structured conclusion. This is only a candidate
    until the Phase 9 deterministic verifier checks it -- the model has
    agency over investigation, not over what reaches GitHub."""

    SPEC_VIOLATION_LIKELY = "spec_violation_likely"
    SPEC_MAY_BE_STALE = "spec_may_be_stale"
    TEST_EVIDENCE_GAP = "test_evidence_gap"
    ARCHITECTURE_VIOLATION_LIKELY = "architecture_violation_likely"
    NO_ISSUE = "no_issue"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
