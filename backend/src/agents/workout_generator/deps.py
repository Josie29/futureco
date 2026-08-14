from dataclasses import dataclass, field
from enum import StrEnum

from neo4j import Session
from pydantic import BaseModel, ConfigDict

from catalog.eligibility import Exclusion
from constraints.diff import ConstraintDiff
from constraints.models import ConstraintSet
from graph.vocabulary import Pass
from resolver.index import ConceptIndex
from resolver.models import Namespace


class ProvenanceKind(StrEnum):
    """What kind of decision a provenance event records."""

    CONCEPT_RESOLUTION = "concept_resolution"
    MEMBER_SNAPSHOT = "member_snapshot"
    CONSTRAINT_DECLARATION = "constraint_declaration"
    CANDIDATE_RETRIEVAL = "candidate_retrieval"
    CLINICAL_ENVELOPE = "clinical_envelope"
    # Grows with the tool belt: validator_verdict, ...


class ProvenanceEvent(BaseModel):
    """One decision the run made, recorded as it happened.

    Every tool call appends here; the plan's trace is assembled from these
    events. Fields beyond `kind` are per-kind and optional until the shapes
    firm up enough to split into a union.
    """

    model_config = ConfigDict(frozen=True)

    kind: ProvenanceKind
    started_ms: float = 0.0
    """Offset from the run's start. Stamped by the toolset's timing wrapper
    after the tool returns — tools themselves never touch the clock."""

    duration_ms: float = 0.0
    query: str | None = None
    namespace: Namespace | None = None
    method: Pass | None = None
    concept: str | None = None
    confidence: float | None = None
    alternatives: tuple[str, ...] = ()
    member: str | None = None
    constraint_set: ConstraintSet | None = None
    constraint_diff: ConstraintDiff | None = None
    rejected_targets: tuple[str, ...] = ()
    candidates: tuple[str, ...] = ()
    """Eligible ids only — this field, and only this field, widens the
    citation allowlist."""

    exclusions: tuple[Exclusion, ...] = ()
    """Never feeds citations; feeds the declared-constraints validator."""

    unmatched_requires: tuple[str, ...] = ()


@dataclass
class GeneratorDeps:
    """Everything one generation run carries that isn't conversation.

    The safety envelope and standing constraints land here once the safety
    package is respecified.
    """

    member_id: str
    duration_min: int
    graph: Session
    """Read-only in effect: tools run module-constant Cypher with typed args,
    never a query string."""

    concept_index: ConceptIndex
    run_began: float = 0.0
    """perf_counter at the run's start, set by generate(). The anchor every
    event's started_ms is measured from."""

    tool_log: list[ProvenanceEvent] = field(default_factory=list)
    declared_constraints: ConstraintSet = field(default_factory=ConstraintSet)
    """The coach-declared set in force, replaced wholesale by
    declare_constraints. Readers consume compose(clinical, declared); the
    declaration diff still runs against this one."""

    clinical_constraints: ConstraintSet = field(default_factory=ConstraintSet)
    """The chart-derived envelope, loaded once by generate(). The tool path
    composes with it; enforce_safety deliberately does not trust it and
    re-loads from the graph."""
