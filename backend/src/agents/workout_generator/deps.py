from dataclasses import dataclass, field
from enum import StrEnum

from neo4j import Session
from pydantic import BaseModel, ConfigDict

from graph.vocabulary import Pass
from resolver.index import ConceptIndex
from resolver.models import Namespace
from resolver.priors import MemberPriors


class ProvenanceKind(StrEnum):
    """What kind of decision a provenance event records."""

    CONCEPT_RESOLUTION = "concept_resolution"
    # Grows with the tool belt: constraint_declaration, envelope_verdict,
    # candidate_retrieval, validator_verdict, ...


class ProvenanceEvent(BaseModel):
    """One decision the run made, recorded as it happened.

    The tool log is the plan's provenance: every tool call appends here, and
    the finished plan's trace is assembled from these events rather than
    reconstructed afterwards. Fields beyond `kind` are per-kind; optional so
    one event type serves the whole belt until the shapes firm up enough to
    split into a union.
    """

    model_config = ConfigDict(frozen=True)

    kind: ProvenanceKind
    query: str | None = None
    namespace: Namespace | None = None
    method: Pass | None = None
    concept: str | None = None
    confidence: float | None = None
    alternatives: tuple[str, ...] = ()


@dataclass
class GeneratorDeps:
    """Everything one generation run carries that isn't conversation.

    Grows with the build-up: the safety envelope (rebuilt only through the
    declare-constraints tool) and standing constraints land here once the
    safety package is respecified.
    """

    member_id: str
    duration_min: int
    graph: Session
    """Read-only in effect: every tool runs module-constant Cypher with typed
    args. No tool signature accepts a query string — enforced by test once
    tools exist."""

    concept_index: ConceptIndex
    member: MemberPriors
    tool_log: list[ProvenanceEvent] = field(default_factory=list)
