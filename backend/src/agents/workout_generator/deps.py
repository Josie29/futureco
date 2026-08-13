from dataclasses import dataclass, field
from enum import StrEnum

from neo4j import Session
from pydantic import BaseModel, ConfigDict

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
    # Grows with the tool belt: envelope_verdict, candidate_retrieval,
    # validator_verdict, ...


class ProvenanceEvent(BaseModel):
    """One decision the run made, recorded as it happened.

    Every tool call appends here; the plan's trace is assembled from these
    events. Fields beyond `kind` are per-kind and optional until the shapes
    firm up enough to split into a union.
    """

    model_config = ConfigDict(frozen=True)

    kind: ProvenanceKind
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
    tool_log: list[ProvenanceEvent] = field(default_factory=list)
    declared_constraints: ConstraintSet = field(default_factory=ConstraintSet)
    """The coach-declared set in force, replaced wholesale by
    declare_constraints. When compose(standing, declared) lands, readers
    consume the composed set but the declaration diff still runs against
    this one."""
